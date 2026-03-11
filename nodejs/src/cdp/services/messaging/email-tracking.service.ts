import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { CyclotronJobInvocationHogFunction, MinimalAppMetric } from '~/cdp/types'
import { RedisV2 } from '~/common/redis/redis-v2'
import { defaultConfig } from '~/config/config'
import { parseJSON } from '~/utils/json-parse'
import { captureException, captureTeamEvent } from '~/utils/posthog'
import { TeamManager } from '~/utils/team-manager'

import { logger } from '../../../utils/logger'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { SesWebhookHandler } from './helpers/ses'
import { generateEmailTrackingCode, generateEmailTrackingPixelUrl } from './helpers/tracking-code'

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
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>,
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

const REPUTATION_REDIS_PREFIX =
    process.env.NODE_ENV === 'test' ? '@posthog-test/email-reputation' : '@posthog/email-reputation'
const REPUTATION_TTL_SECONDS = 86400 // 24h sliding window

const BOUNCE_RATE_THRESHOLD = 0.02 // 2% — Google/Yahoo enforcement threshold
const COMPLAINT_RATE_THRESHOLD = 0.001 // 0.1% — SES suspension threshold
const MIN_SENDS_FOR_RATE_CHECK = 250 // avoid false positives on low volume

export class EmailTrackingService {
    private sesWebhookHandler: SesWebhookHandler

    constructor(
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService,
        private redis: RedisV2,
        private teamManager: TeamManager
    ) {
        this.sesWebhookHandler = new SesWebhookHandler()
    }

    public async trackMetric({
        functionId,
        invocationId,
        metricName,
        source,
    }: {
        functionId?: string
        invocationId?: string
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
                app_source_id: appSourceId,
                instance_id: invocationId,
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

    private reputationKey(hogFlowId: string, counter: 'sends' | 'bounces' | 'complaints' | 'alerted'): string {
        return `${REPUTATION_REDIS_PREFIX}/${hogFlowId}/${counter}`
    }


    private async incrementWithTtl(key: string): Promise<number> {
        const count = await this.redis.useClient({ name: 'email-reputation-incr', failOpen: true }, async (client) => {
            // Use Lua script to atomically incr and set expire on first write
            const script = `
                local val = redis.call('INCR', KEYS[1])
                if val == 1 then
                    redis.call('EXPIRE', KEYS[1], ARGV[1])
                end
                return val
            `
            return await client.eval(script, 1, key, REPUTATION_TTL_SECONDS)
        })
        return count ?? 0
    }


    private async checkAndMaybeDisableWorkflow(hogFlowId: string, teamId: number): Promise<void> {
        const [sendsRaw, bouncesRaw, complaintsRaw] = (await this.redis.useClient(
            { name: 'email-reputation-check', failOpen: true },
            async (client) =>
                client.mget(
                    this.reputationKey(hogFlowId, 'sends'),
                    this.reputationKey(hogFlowId, 'bounces'),
                    this.reputationKey(hogFlowId, 'complaints')
                )
        )) ?? [null, null, null]

        const sends = parseInt(sendsRaw ?? '0', 10)
        const bounces = parseInt(bouncesRaw ?? '0', 10)
        const complaints = parseInt(complaintsRaw ?? '0', 10)

        const bounceRate = sends > 0 ? bounces / sends : 0
        const complaintRate = sends > 0 ? complaints / sends : 0

        const rateBreach =
            sends >= MIN_SENDS_FOR_RATE_CHECK &&
            (bounceRate >= BOUNCE_RATE_THRESHOLD || complaintRate >= COMPLAINT_RATE_THRESHOLD)

        if (!rateBreach) {
            return
        }

        // Use SETNX as a distributed once-per-window guard — only the first call within the TTL fires the event
        const alertKey = this.reputationKey(hogFlowId, 'alerted')

        const isFirstAlert = await this.redis.useClient(
            { name: 'email-reputation-alert', failOpen: true },
            async (client) => {
                const script = `
                    local set = redis.call('SETNX', KEYS[1], ARGV[1])
                    if set == 1 then
                        redis.call('EXPIRE', KEYS[1], ARGV[2])
                    end
                    return set
                `
                return (await client.eval(script, 1, alertKey, '1', REPUTATION_TTL_SECONDS)) === 1
            }
        )


        if (!isFirstAlert) {
            return
        }

        const team = await this.teamManager.getTeam(teamId)
        if (!team) {
            logger.error('[EmailTrackingService] checkAndMaybeDisableWorkflow: team not found', { teamId, hogFlowId })
            return
        }

        const disabled = await this.hogFlowManager.disableHogFlow(hogFlowId)

        captureTeamEvent(team, 'email_workflow_paused_for_reputation', {
            workflow_id: hogFlowId,
            bounce_rate: bounceRate,
            complaint_rate: complaintRate,
            bounces,
            complaints,
            sends,
            disabled,
        })

        logger.info('[EmailTrackingService] Email reputation threshold breached', {
            hogFlowId,
            teamId,
            bounces,
            complaints,
            sends,
            bounceRate,
            complaintRate,
        })
    }

    private async trackReputation(
        hogFlowId: string,
        teamId: number,
        metricName: MinimalAppMetric['metric_name']
    ): Promise<void> {
        if (metricName === 'email_sent') {
            await this.incrementWithTtl(this.reputationKey(hogFlowId, 'sends'))
        } else if (metricName === 'email_bounced') {
            await this.incrementWithTtl(this.reputationKey(hogFlowId, 'bounces'))
            await this.checkAndMaybeDisableWorkflow(hogFlowId, teamId)
        } else if (metricName === 'email_blocked') {
            await this.incrementWithTtl(this.reputationKey(hogFlowId, 'complaints'))
            await this.checkAndMaybeDisableWorkflow(hogFlowId, teamId)
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
                    metricName: metric.metricName,
                    source: 'ses',
                })

                if (metric.functionId) {
                    const hogFlow = await this.hogFlowManager.getHogFlow(metric.functionId).catch(() => null)
                    if (hogFlow) {
                        await this.trackReputation(hogFlow.id, hogFlow.team_id, metric.metricName)
                    }
                }
            }

            return { status, message: body as string }
        } catch (error) {
            emailTrackingErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: SES webhook error', { error })
            throw error
        }
    }

    public async handleEmailTrackingPixel(req: ModifiedRequest, res: express.Response): Promise<void> {
        // NOTE: this is somewhat naieve. We should expand with UA checking for things like apple's tracking prevention etc.
        const { ph_fn_id, ph_inv_id } = req.query

        // Track the value
        try {
            await this.trackMetric({
                functionId: ph_fn_id as string,
                invocationId: ph_inv_id as string,
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
        const { ph_fn_id, ph_inv_id, target } = req.query

        if (!target) {
            res.status(404).send('Not found')
            return
        }

        // Track the value
        try {
            await this.trackMetric({
                functionId: ph_fn_id as string,
                invocationId: ph_inv_id as string,
                metricName: 'email_link_clicked',
                source: 'direct',
            })
        } catch (error) {
            logger.error('[EmailTrackingService] handleEmailTrackingRedirect: Error tracking metric', { error })
            captureException(error)
        }

        res.redirect(target as string)
    }
}
