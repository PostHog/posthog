import { DateTime } from 'luxon'
import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { HogFlow } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFunction, LogEntry, LogEntryLevel, MinimalAppMetric } from '~/cdp/types'
import { ModifiedRequest } from '~/common/api/router'
import { isDevEnv, isTestEnv } from '~/common/utils/env-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { CapturedEventsService } from '../captured-events/captured-events.service'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { SesWebhookHandler } from './helpers/ses'
import { EmailTrackingCodeSigner, trackingCodeFormatCounter } from './helpers/tracking-code'

export const PIXEL_GIF = Buffer.from('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==', 'base64')
const LINK_REGEX =
    /<a\b[^>]*\bhref\s*=\s*(?:"(?!javascript:)([^"]*)"|'(?!javascript:)([^']*)'|(?!javascript:)([^'">\s]+))[^>]*>([\s\S]*?)<\/a>/gi

// Anchors carrying either opt-out marker are left unwrapped (no click-tracking redirect).
const LINK_TRACKING_OPT_OUT_REGEX = /\bclicktracking\s*=\s*["']?off["']?|\bdata-ph-no-track\b/i

const trackingEventsCounter = new Counter({
    name: 'email_tracking_events_total',
    help: 'Total number of email tracking events received',
    labelNames: ['event_type', 'source'],
})

const emailTrackingErrorsCounter = new Counter({
    name: 'email_tracking_errors_total',
    help: 'Total number of email tracking processing errors',
    labelNames: ['error_type', 'source'],
})

// Skips here are expected (e.g. SES webhook for a hog_function rather than a hog_flow),
// kept separate so alerts on `email_tracking_errors_total` don't fire on normal traffic.
const emailTrackingLogSkipsCounter = new Counter({
    name: 'email_tracking_log_skips_total',
    help: 'Total number of email tracking log entries skipped (expected, non-error)',
    labelNames: ['reason', 'source'],
})

// Allowlist of metrics that surface as PostHog events when engagement-event capture is enabled.
// Metrics not in this map are deliberately ignored (no `$messaging_${metricName}` fallback) so a new
// internal metric can't silently leak into customers' event streams.
export const METRIC_NAME_TO_EVENT_NAME: Partial<Record<MinimalAppMetric['metric_name'], string>> = {
    email_sent: '$workflows_email_sent',
    email_failed: '$workflows_email_failed',
    email_delivered: '$workflows_email_delivered',
    email_opened: '$workflows_email_opened',
    email_link_clicked: '$workflows_email_link_clicked',
    email_bounced: '$workflows_email_bounced',
    email_blocked: '$workflows_email_blocked',
}

/**
 * Resolve the identifier to attribute engagement events to. `event.distinct_id` is the canonical
 * source for both flows: event-triggered runs carry it from the trigger event, and batch/scheduled
 * runs have it backfilled by the cyclotron worker from the person's resolved distinct_id (see the
 * `getCyclotronPerson` backfill in cdp-cyclotron-worker-hogflow.consumer.ts). We deliberately do
 * NOT derive it from `globals.person` — `person.id` is the person UUID, which was never ingested as
 * a distinct_id and would mint a phantom person, and `person.distinct_id` is the same source already
 * folded into `event.distinct_id` upstream. If there's no distinct_id we skip capture rather than
 * emit an unattributable event.
 */
export const resolveEmailEngagementDistinctId = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'state'>
): string | undefined => {
    return invocation.state?.globals?.event?.distinct_id || undefined
}

// HTML attribute values arrive entity-encoded (e.g. `&amp;`, `&#38;`). Decode before
// percent-encoding for the tracking redirect, otherwise `?a=1&amp;b=2` round-trips
// through `target=` as a literal `&amp;` and breaks the destination page's query string.
const HTML_ENTITY_REGEX = /&(?:(amp|lt|gt|quot|apos)|#(\d+)|#x([0-9a-fA-F]+));/g
const NAMED_ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }

export const decodeHtmlEntitiesInHref = (value: string): string => {
    return value.replace(HTML_ENTITY_REGEX, (_match, named, dec, hex) => {
        if (named) {
            return NAMED_ENTITIES[named]
        }
        const code = dec ? parseInt(dec, 10) : parseInt(hex, 16)
        // `String.fromCodePoint` throws RangeError above 0x10FFFF — `Number.isFinite` alone
        // wouldn't catch e.g. `&#x200000;` since `parseInt` happily returns a finite value.
        return code >= 0 && code <= 0x10ffff ? String.fromCodePoint(code) : _match
    })
}

export const addTrackingToEmail = (
    html: string,
    invocation: CyclotronJobInvocationHogFunction,
    signer: EmailTrackingCodeSigner,
    isTest = false
): string => {
    // Only carry distinct_id in the in-email pixel/redirect URLs in dev/test, where those handlers
    // record metrics. In production they don't (SES webhooks own open/click attribution via the
    // signed header), so embedding distinct_id in the public `ph_id` would be unused — and worse,
    // a tracked-link click could leak the recipient identifier to the destination via the Referer.
    const distinctId = isDevEnv() || isTestEnv() ? resolveEmailEngagementDistinctId(invocation) : undefined
    const trackingInvocation = { ...invocation, distinctId }
    const trackingUrl = signer.pixelUrl(trackingInvocation, isTest)

    html = html.replace(LINK_REGEX, (m, d, s, u) => {
        const href = decodeHtmlEntitiesInHref(d || s || u || '')
        // LINK_REGEX skips literal `javascript:` hrefs, but an attacker could entity-encode
        // the scheme (e.g. `java&#x73;cript:`) to slip past it; re-check after decoding.
        if (/^\s*javascript:/i.test(href)) {
            return m
        }
        // Per-link opt-out. Leaves the href on its own domain so mobile universal links /
        // app deeplinks resolve - routing through our cross-domain redirect breaks them.
        // `clicktracking="off"` is the ESP de-facto standard; `data-ph-no-track` is our name.
        // Match only the opening <a> tag so a marker in the link's inner HTML (a child
        // element's attribute or literal link text) can't silently disable tracking.
        const openingTag = m.match(/^<a\b[^>]*>/i)?.[0] ?? ''
        if (LINK_TRACKING_OPT_OUT_REGEX.test(openingTag)) {
            return m
        }
        const tracked = signer.redirectUrl(trackingInvocation, href, isTest)

        // replace just the href in the original tag to preserve other attributes
        return m.replace(/\bhref\s*=\s*(?:"[^"]*"|'[^']*'|[^'">\s]+)/i, `href="${tracked}"`)
    })

    html = html.replace('</body>', `<img src="${trackingUrl}" style="display: none;" /></body>`)

    return html
}

export class EmailTrackingService {
    private sesWebhookHandler: SesWebhookHandler

    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService,
        private capturedEventsService: CapturedEventsService,
        private teamWorkflowsConfigService: TeamWorkflowsConfigService,
        private recipientsManager: RecipientsManagerService,
        private trackingCodeSigner: EmailTrackingCodeSigner
    ) {
        this.sesWebhookHandler = new SesWebhookHandler(this.trackingCodeSigner)
    }

    public async trackMetric({
        functionId,
        invocationId,
        actionId,
        parentRunId,
        distinctId,
        metricName,
        source,
        properties,
        timestamp,
    }: {
        functionId?: string
        invocationId?: string
        actionId?: string
        parentRunId?: string
        distinctId?: string
        metricName: MinimalAppMetric['metric_name']
        source: 'direct' | 'ses'
        properties?: Record<string, unknown>
        timestamp?: string
    }): Promise<void> {
        if (!functionId || !invocationId) {
            logger.error('[EmailTrackingService] trackMetric: Invalid custom ID', {
                functionId,
                invocationId,
                metricName,
            })
            emailTrackingErrorsCounter.inc({ error_type: 'invalid_custom_id', source })
            return
        }

        // The function ID could be one or the other so we load both
        const [hogFunction, hogFlow] = await Promise.all([
            this.hogFunctionManager.getHogFunction(functionId).catch(() => null),
            this.hogFlowManager.getHogFlow(functionId).catch(() => null),
        ])

        const teamId = hogFunction?.team_id ?? hogFlow?.team_id
        const appSourceId = hogFunction?.id ?? hogFlow?.id

        if (!teamId || !appSourceId) {
            logger.error('[EmailTrackingService] trackMetric: Hog function or flow not found', {
                functionId,
                invocationId,
                source,
            })
            emailTrackingErrorsCounter.inc({ error_type: 'hog_function_or_flow_not_found', source })
            return
        }

        this.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: teamId,
                // Mirror email.service.ts's `parentRunId ?? functionId` so batch-triggered
                // runs get their webhook metrics attributed to the batch run, not the workflow.
                app_source_id: parentRunId ?? appSourceId,
                instance_id: actionId || invocationId,
                metric_name: metricName,
                metric_kind: 'email',
                count: 1,
            },
            hogFlow ? 'hog_flow' : 'hog_function'
        )

        const eventName = METRIC_NAME_TO_EVENT_NAME[metricName]
        if (eventName && distinctId && (await this.teamWorkflowsConfigService.shouldCaptureEngagementEvents(teamId))) {
            await this.capturedEventsService.queueEvent({
                team_id: teamId,
                event: eventName,
                distinct_id: distinctId,
                timestamp,
                properties: {
                    $workflow_id: appSourceId,
                    $workflow_action_id: actionId,
                    ...properties,
                },
            })
            await this.capturedEventsService.flush()
        }

        await this.hogFunctionMonitoringService.flush()

        trackingEventsCounter.inc({ event_type: metricName, source })
        logger.debug('[EmailTrackingService] trackMetric: Email tracking event', {
            functionId,
            invocationId,
            metricName,
        })
    }

    public async trackLogs(
        entries: {
            functionId?: string
            invocationId?: string
            parentRunId?: string
            level: LogEntryLevel
            message: string
        }[]
    ): Promise<void> {
        if (entries.length === 0) {
            return
        }

        const uniqueFunctionIds = Array.from(
            new Set(entries.map((e) => e.functionId).filter((id): id is string => Boolean(id)))
        )

        let hogFlows: Record<string, HogFlow | null> = {}
        try {
            hogFlows = await this.hogFlowManager.getHogFlows(uniqueFunctionIds)
        } catch (error) {
            logger.error('[EmailTrackingService] trackLogs: Failed to load hog flows', { error })
            emailTrackingErrorsCounter.inc({ error_type: 'hog_flow_lookup_failed', source: 'ses' })
            return
        }

        const now = DateTime.utc()
        const logEntries: LogEntry[] = []
        for (const entry of entries) {
            if (!entry.functionId || !entry.invocationId) {
                logger.error('[EmailTrackingService] trackLogs: Invalid custom ID', {
                    functionId: entry.functionId,
                    invocationId: entry.invocationId,
                })
                emailTrackingErrorsCounter.inc({ error_type: 'invalid_custom_id', source: 'ses' })
                continue
            }

            const hogFlow = hogFlows[entry.functionId]
            if (!hogFlow) {
                emailTrackingLogSkipsCounter.inc({ reason: 'non_flow', source: 'ses' })
                continue
            }

            logEntries.push({
                team_id: hogFlow.team_id,
                log_source: 'hog_flow',
                // Batch-triggered runs log under the batch run id (parentRunId); mirror the metrics path.
                log_source_id: entry.parentRunId ?? hogFlow.id,
                instance_id: entry.invocationId,
                timestamp: now,
                level: entry.level,
                message: entry.message,
            })
        }

        if (logEntries.length === 0) {
            return
        }

        this.hogFunctionMonitoringService.queueLogs(logEntries, 'hog_flow')
        await this.hogFunctionMonitoringService.flush()
    }

    public async handleSesWebhook(req: ModifiedRequest): Promise<{ status: number; message?: string }> {
        if (!req.body) {
            return { status: 403, message: 'Missing request body' }
        }

        try {
            const { status, body, metrics, logEntries, optOutRecipients } = await this.sesWebhookHandler.handleWebhook({
                body: parseJSON(req.body),
                headers: req.headers,
                verifySignature: true,
            })

            for (const metric of metrics || []) {
                await this.trackMetric({
                    functionId: metric.functionId,
                    invocationId: metric.invocationId,
                    actionId: metric.actionId,
                    parentRunId: metric.parentRunId,
                    distinctId: metric.distinctId,
                    metricName: metric.metricName,
                    source: 'ses',
                    properties: metric.properties,
                    timestamp: metric.timestamp,
                })
            }

            // Wrapped so a failure here doesn't skip the opt-out processing below.
            try {
                await this.trackLogs(
                    (logEntries || []).map((entry) => ({
                        functionId: entry.functionId,
                        invocationId: entry.invocationId,
                        parentRunId: entry.parentRunId,
                        level: entry.level,
                        message: entry.message,
                    }))
                )
            } catch (error) {
                logger.error('[EmailTrackingService] handleSesWebhook: Failed to track logs', { error })
                emailTrackingErrorsCounter.inc({ error_type: 'track_logs_failed', source: 'ses' })
            }

            // Collect all emails to opt out per team, then batch each team's opt-out in one query
            const emailsByTeam = new Map<number, string[]>()
            for (const { teamId: teamIdStr, emailAddresses } of optOutRecipients || []) {
                const teamId = teamIdStr ? parseInt(teamIdStr, 10) : NaN
                if (!teamId || isNaN(teamId)) {
                    logger.error('[EmailTrackingService] handleSesWebhook: Missing or invalid teamId for opt-out', {
                        teamIdStr,
                        emailAddresses,
                    })
                    continue
                }
                const existing = emailsByTeam.get(teamId) ?? []
                existing.push(...emailAddresses)
                emailsByTeam.set(teamId, existing)
            }

            for (const [teamId, emails] of emailsByTeam) {
                try {
                    await this.recipientsManager.optOut(teamId, emails)
                    logger.info('[EmailTrackingService] Opted out recipients after a hard bounce', {
                        teamId,
                        emails,
                    })
                } catch (error) {
                    logger.error('[EmailTrackingService] Failed to opt out recipients', {
                        teamId,
                        emails,
                        error,
                    })
                }
            }

            return { status, message: body as string }
        } catch (error) {
            emailTrackingErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: SES webhook error', { error })
            throw error
        }
    }

    private parseTrackingParams(query: Record<string, any>): {
        functionId?: string
        invocationId?: string
        actionId?: string
        parentRunId?: string
        distinctId?: string
    } {
        // Support both combined ph_id format and legacy separate params
        if (query.ph_id) {
            const parsed = this.trackingCodeSigner.parse(query.ph_id as string)
            if (parsed) {
                trackingCodeFormatCounter.inc({ format: parsed.format, source: 'tracking' })
            }
            return {
                functionId: parsed?.functionId,
                invocationId: parsed?.invocationId,
                actionId: parsed?.actionId,
                parentRunId: parsed?.parentRunId,
                distinctId: parsed?.distinctId,
            }
        }
        return {
            functionId: query.ph_fn_id as string | undefined,
            invocationId: query.ph_inv_id as string | undefined,
        }
    }

    // NOTE: this is somewhat naieve. We should expand with UA checking for things like apple's tracking prevention etc.
    // In production, opens are tracked via SES webhooks — recording here would double-count.
    // In dev/test (where maildev replaces SES and no webhooks come back), we fire the
    // engagement event from the pixel handler so local testing produces real events.
    public handleEmailTrackingPixel(req: ModifiedRequest, res: express.Response): void {
        res.status(200).set('Content-Type', 'image/gif').send(PIXEL_GIF)

        if (isDevEnv() || isTestEnv()) {
            const params = this.parseTrackingParams(req.query as Record<string, any>)
            void this.trackMetric({ ...params, metricName: 'email_opened', source: 'direct' }).catch((error) => {
                logger.error('[EmailTrackingService] handleEmailTrackingPixel: trackMetric failed', { error })
            })
        }
    }

    // Same rationale as handleEmailTrackingPixel: skip in production (SES webhooks own
    // click tracking), but emit in dev/test where maildev never produces webhooks.
    public handleEmailTrackingRedirect(req: ModifiedRequest, res: express.Response): void {
        const { target } = req.query

        if (!target) {
            res.status(404).send('Not found')
            return
        }

        res.redirect(target as string)

        if (isDevEnv() || isTestEnv()) {
            const params = this.parseTrackingParams(req.query as Record<string, any>)
            void this.trackMetric({ ...params, metricName: 'email_link_clicked', source: 'direct' }).catch((error) => {
                logger.error('[EmailTrackingService] handleEmailTrackingRedirect: trackMetric failed', { error })
            })
        }
    }
}
