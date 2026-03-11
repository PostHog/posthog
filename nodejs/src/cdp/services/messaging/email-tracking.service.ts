import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { CyclotronJobInvocationHogFunction, MinimalAppMetric } from '~/cdp/types'
import { defaultConfig } from '~/config/config'
import { parseJSON } from '~/utils/json-parse'
import { captureException } from '~/utils/posthog'

import { logger } from '../../../utils/logger'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
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

const METRIC_NAME_TO_EVENT_NAME: Partial<Record<MinimalAppMetric['metric_name'], string>> = {
    email_sent: '$messaging_email_sent',
    email_failed: '$messaging_email_failed',
    email_opened: '$messaging_email_opened',
    email_link_clicked: '$messaging_email_link_clicked',
    email_bounced: '$messaging_email_bounced',
    email_blocked: '$messaging_email_blocked',
    email_spam: '$messaging_email_spam',
    email_unsubscribed: '$messaging_email_unsubscribed',
}

export { METRIC_NAME_TO_EVENT_NAME }

export const generateTrackingRedirectUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>,
    targetUrl: string,
    distinctId?: string
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/redirect?ph_id=${generateEmailTrackingCode(invocation, distinctId)}&target=${encodeURIComponent(targetUrl)}`
}

export const addTrackingToEmail = (html: string, invocation: CyclotronJobInvocationHogFunction): string => {
    const distinctId = invocation.state?.globals?.event?.distinct_id
    const trackingUrl = generateEmailTrackingPixelUrl(invocation, distinctId)

    html = html.replace(LINK_REGEX, (m, d, s, u) => {
        const href = d || s || u || ''
        const tracked = generateTrackingRedirectUrl(invocation, href, distinctId)

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
        private hogFunctionMonitoringService: HogFunctionMonitoringService
    ) {
        this.sesWebhookHandler = new SesWebhookHandler()
    }

    public async trackMetric({
        functionId,
        invocationId,
        distinctId,
        metricName,
        source,
        properties,
    }: {
        functionId?: string
        invocationId?: string
        distinctId?: string
        metricName: MinimalAppMetric['metric_name']
        source: 'direct' | 'ses'
        properties?: Record<string, any>
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
                app_source_id: appSourceId,
                instance_id: invocationId,
                metric_name: metricName,
                metric_kind: 'email',
                count: 1,
            },
            hogFlow ? 'hog_flow' : 'hog_function'
        )

        if (distinctId) {
            this.hogFunctionMonitoringService.queuePostHogEvent({
                team_id: teamId,
                distinct_id: distinctId,
                event: METRIC_NAME_TO_EVENT_NAME[metricName] ?? `$messaging_${metricName}`,
                properties: {
                    $workflow_id: appSourceId,
                    $messaging_source: source,
                    ...properties,
                },
            })
        }

        await this.hogFunctionMonitoringService.flush()

        trackingEventsCounter.inc({ event_type: metricName, source })
        logger.debug('[EmailTrackingService] trackMetric: Email tracking event', {
            functionId,
            invocationId,
            metricName,
        })
    }

    private parseTrackingParams(query: Record<string, any>): {
        functionId?: string
        invocationId?: string
        distinctId?: string
    } {
        // Support both combined ph_id format and legacy separate params
        if (query.ph_id) {
            const parsed = parseEmailTrackingCode(query.ph_id as string)
            return {
                functionId: parsed?.functionId,
                invocationId: parsed?.invocationId,
                distinctId: parsed?.distinctId,
            }
        }
        return {
            functionId: query.ph_fn_id as string | undefined,
            invocationId: query.ph_inv_id as string | undefined,
        }
    }

    public async handleSesWebhook(req: ModifiedRequest): Promise<{ status: number; message?: string }> {
        if (!req.body) {
            return { status: 403, message: 'Missing request body' }
        }

        try {
            const { status, body, metrics } = await this.sesWebhookHandler.handleWebhook({
                body: parseJSON(req.body),
                headers: req.headers,
                verifySignature: true,
            })

            for (const metric of metrics || []) {
                await this.trackMetric({
                    functionId: metric.functionId,
                    invocationId: metric.invocationId,
                    distinctId: metric.distinctId,
                    metricName: metric.metricName,
                    source: 'ses',
                    properties: metric.properties,
                })
            }

            return { status, message: body as string }
        } catch (error) {
            emailTrackingErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: SES webhook error', { error })
            throw error
        }
    }

    public async handleEmailTrackingPixel(req: ModifiedRequest, res: express.Response): Promise<void> {
        const { functionId, invocationId, distinctId } = this.parseTrackingParams(req.query)

        try {
            await this.trackMetric({
                functionId,
                invocationId,
                distinctId,
                metricName: 'email_opened',
                source: 'direct',
            })
        } catch (error) {
            logger.error('[EmailTrackingService] handleEmailTrackingPixel: Error tracking open metric', { error })
            captureException(error)
        }

        res.status(200).set('Content-Type', 'image/gif').send(PIXEL_GIF)
    }

    public async handleEmailTrackingRedirect(req: ModifiedRequest, res: express.Response): Promise<void> {
        const { functionId, invocationId, distinctId } = this.parseTrackingParams(req.query)
        const { target } = req.query

        if (!target) {
            res.status(404).send('Not found')
            return
        }

        try {
            await this.trackMetric({
                functionId,
                invocationId,
                distinctId,
                metricName: 'email_link_clicked',
                source: 'direct',
                properties: { $link_url: target },
            })
        } catch (error) {
            logger.error('[EmailTrackingService] handleEmailTrackingRedirect: Error tracking metric', { error })
            captureException(error)
        }

        res.redirect(target as string)
    }
}
