import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { CyclotronJobInvocationHogFunction, MinimalAppMetric } from '~/cdp/types'
import { defaultConfig } from '~/config/config'
import { parseJSON } from '~/utils/json-parse'

import { logger } from '../../../utils/logger'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { SesWebhookHandler } from './helpers/ses'
import {
    generateEmailTrackingCode,
    generateEmailTrackingPixelUrl,
    parseEmailTrackingCode,
} from './helpers/tracking-code'

export const PIXEL_GIF = Buffer.from('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==', 'base64')
const LINK_REGEX =
    /<a\b[^>]*\bhref\s*=\s*(?:"(?!javascript:)([^"]*)"|'(?!javascript:)([^']*)'|(?!javascript:)([^'">\s]+))[^>]*>([\s\S]*?)<\/a>/gi

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

export const generateTrackingRedirectUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id' | 'teamId'> & {
        parentRunId?: string | null
        state?: { actionId?: string }
    },
    targetUrl: string
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/redirect?ph_id=${generateEmailTrackingCode(invocation)}&target=${encodeURIComponent(targetUrl)}`
}

export const addTrackingToEmail = (html: string, invocation: CyclotronJobInvocationHogFunction): string => {
    const trackingUrl = generateEmailTrackingPixelUrl(invocation)

    html = html.replace(LINK_REGEX, (m, d, s, u) => {
        const href = d || s || u || ''
        const tracked = generateTrackingRedirectUrl(invocation, href)

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
        private recipientsManager: RecipientsManagerService
    ) {
        this.sesWebhookHandler = new SesWebhookHandler()
    }

    public async trackMetric({
        functionId,
        invocationId,
        actionId,
        parentRunId,
        metricName,
        source,
    }: {
        functionId?: string
        invocationId?: string
        actionId?: string
        parentRunId?: string
        metricName: MinimalAppMetric['metric_name']
        source: 'direct' | 'ses'
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

        await this.hogFunctionMonitoringService.flush()

        trackingEventsCounter.inc({ event_type: metricName, source })
        logger.debug('[EmailTrackingService] trackMetric: Email tracking event', {
            functionId,
            invocationId,
            metricName,
        })
    }

    public async handleSesWebhook(req: ModifiedRequest): Promise<{ status: number; message?: string }> {
        if (!req.body) {
            return { status: 403, message: 'Missing request body' }
        }

        try {
            const { status, body, metrics, optOutRecipients } = await this.sesWebhookHandler.handleWebhook({
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
                    metricName: metric.metricName,
                    source: 'ses',
                })
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
    } {
        // Support both combined ph_id format and legacy separate params
        if (query.ph_id) {
            const parsed = parseEmailTrackingCode(query.ph_id as string)
            return {
                functionId: parsed?.functionId,
                invocationId: parsed?.invocationId,
                actionId: parsed?.actionId,
                parentRunId: parsed?.parentRunId,
            }
        }
        return {
            functionId: query.ph_fn_id as string | undefined,
            invocationId: query.ph_inv_id as string | undefined,
        }
    }

    // NOTE: this is somewhat naieve. We should expand with UA checking for things like apple's tracking prevention etc.
    // Metrics are not recorded here because SES webhooks already track opens.
    // Recording here would double-count. The pixel is still served so email
    // clients that load it get a valid response.
    public handleEmailTrackingPixel(_req: ModifiedRequest, res: express.Response): void {
        res.status(200).set('Content-Type', 'image/gif').send(PIXEL_GIF)
    }

    // Metrics are not recorded here because SES webhooks already track clicks.
    // Recording here would double-count. The redirect still works so users
    // reach their destination.
    public handleEmailTrackingRedirect(req: ModifiedRequest, res: express.Response): void {
        const { target } = req.query

        if (!target) {
            res.status(404).send('Not found')
            return
        }

        res.redirect(target as string)
    }
}
