import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { webAnalyticsRecap } from 'products/web_analytics/frontend/generated/api'
import type { WebAnalyticsRecapResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { formatRecapDateRange } from './recapDates'
import type { webAnalyticsRecapLogicType } from './webAnalyticsRecapLogicType'

export type RecapShareMethod = 'copy_link' | 'copy_slack' | 'copy_email'
export type RecapCta = 'view_dashboard' | 'ask_posthog_ai' | 'go_to_web_analytics'
export type RecapButton = RecapShareMethod | RecapCta
type RecapButtonIntent = 'share' | 'web_analytics_view' | 'posthog_ai_usage'
type RecapButtonDestination = 'clipboard' | 'web_analytics_dashboard' | 'posthog_ai_side_panel'
type RecapEventProperties = Record<string, string | number | boolean | null>

// Matches the existing weekly digest cadence — the recap is the weekly moment, not a custom range.
const RECAP_DAYS = 7

const WEB_ANALYTICS_RECAP_DASHBOARD_PARAMS = {
    utm_source: 'web_analytics_recap',
    utm_medium: 'recap_button',
    utm_campaign: 'weekly_recap',
}

function buildSlackCopy(recap: WebAnalyticsRecapResponseApi): string {
    return [
        `*${recap.project_name} website recap*`,
        formatRecapDateRange(recap),
        '',
        `• ${recap.visitors.current.toLocaleString()} visitors`,
        `• ${recap.pageviews.current.toLocaleString()} pageviews`,
        `• ${recap.sessions.current.toLocaleString()} sessions`,
        `• ${Math.round(recap.bounce_rate.current)}% bounce rate`,
        '',
        `Persona: ${recap.persona.emoji} ${recap.persona.name}`,
        recap.recap_url,
    ].join('\n')
}

function buildEmailCopy(recap: WebAnalyticsRecapResponseApi): string {
    return [
        `Subject: ${recap.project_name} website recap: ${formatRecapDateRange(recap)}`,
        '',
        `Here's the website recap for ${recap.project_name} (${formatRecapDateRange(recap)}):`,
        '',
        `${recap.visitors.current.toLocaleString()} visitors`,
        `${recap.pageviews.current.toLocaleString()} pageviews`,
        `${recap.sessions.current.toLocaleString()} sessions`,
        `${Math.round(recap.bounce_rate.current)}% bounce rate`,
        '',
        `This week's persona: ${recap.persona.emoji} ${recap.persona.name}`,
        recap.persona.blurb,
        '',
        `View the full recap: ${recap.recap_url}`,
    ].join('\n')
}

export const webAnalyticsRecapLogic = kea<webAnalyticsRecapLogicType>([
    path(['scenes', 'web-analytics', 'recap', 'webAnalyticsRecapLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        recordOpened: true,
        recordReachedEnd: true,
        recordButtonClicked: (button: RecapButton) => ({ button }),
        recordShared: (method: RecapShareMethod) => ({ method }),
        recordCtaClicked: (cta: RecapCta) => ({ cta }),
        copyRecapLink: true,
        copyRecapForSlack: true,
        copyRecapForEmail: true,
        goToWebAnalytics: (cta: Extract<RecapCta, 'view_dashboard' | 'go_to_web_analytics'>) => ({ cta }),
    }),
    loaders(({ values }) => ({
        recap: [
            null as WebAnalyticsRecapResponseApi | null,
            {
                loadRecap: async () => {
                    const projectId = values.currentProjectId
                    if (projectId == null) {
                        return null
                    }
                    return await webAnalyticsRecap(String(projectId), { days: RECAP_DAYS })
                },
            },
        ],
    })),
    listeners(({ values, actions }) => {
        const recapProperties = (): RecapEventProperties => {
            const recap = values.recap
            return {
                project_id: values.currentProjectId ?? null,
                period_label: recap?.period_label ?? null,
                period_start: recap?.period_start ?? null,
                period_end: recap?.period_end ?? null,
                persona: recap?.persona.id ?? null,
                visitors: recap?.visitors.current ?? null,
                pageviews: recap?.pageviews.current ?? null,
                sessions: recap?.sessions.current ?? null,
                top_pages_count: recap?.top_pages.length ?? null,
                top_sources_count: recap?.top_sources.length ?? null,
                goals_count: recap?.goals.length ?? null,
                highlights_count: recap?.highlights.length ?? null,
            }
        }

        const buttonContext = (
            button: RecapButton
        ): { intent: RecapButtonIntent; destination: RecapButtonDestination } => {
            if (button === 'copy_link' || button === 'copy_slack' || button === 'copy_email') {
                return { intent: 'share', destination: 'clipboard' }
            }
            if (button === 'ask_posthog_ai') {
                return { intent: 'posthog_ai_usage', destination: 'posthog_ai_side_panel' }
            }
            return { intent: 'web_analytics_view', destination: 'web_analytics_dashboard' }
        }

        return {
            recordOpened: () => {
                const { utm_source, utm_medium } = router.values.searchParams
                posthog.capture('web_analytics_recap_opened', {
                    utm_source: utm_source ?? null,
                    utm_medium: utm_medium ?? null,
                    ...recapProperties(),
                })
            },
            loadRecapSuccess: () => {
                if (values.recap?.persona) {
                    posthog.capture('web_analytics_recap_persona_assigned', {
                        ...recapProperties(),
                        persona: values.recap.persona.id,
                    })
                }
            },
            recordReachedEnd: () => {
                posthog.capture('web_analytics_recap_completed', recapProperties())
            },
            recordButtonClicked: ({ button }) => {
                posthog.capture('web_analytics_recap_button_clicked', {
                    ...recapProperties(),
                    button,
                    ...buttonContext(button),
                })
            },
            recordShared: ({ method }) => {
                posthog.capture('web_analytics_recap_shared', {
                    ...recapProperties(),
                    method,
                })
            },
            recordCtaClicked: ({ cta }) => {
                actions.recordButtonClicked(cta)
                posthog.capture('web_analytics_recap_cta_clicked', {
                    ...recapProperties(),
                    cta,
                })
            },
            copyRecapLink: async () => {
                actions.recordButtonClicked('copy_link')
                const url = values.recap?.recap_url ?? window.location.href
                if (await copyToClipboard(url, 'recap link')) {
                    actions.recordShared('copy_link')
                }
            },
            copyRecapForSlack: async () => {
                if (!values.recap) {
                    return
                }
                actions.recordButtonClicked('copy_slack')
                if (await copyToClipboard(buildSlackCopy(values.recap), 'Slack recap')) {
                    actions.recordShared('copy_slack')
                }
            },
            copyRecapForEmail: async () => {
                if (!values.recap) {
                    return
                }
                actions.recordButtonClicked('copy_email')
                if (await copyToClipboard(buildEmailCopy(values.recap), 'email recap')) {
                    actions.recordShared('copy_email')
                }
            },
            goToWebAnalytics: ({ cta }) => {
                actions.recordCtaClicked(cta)
                router.actions.push(urls.webAnalytics(), {
                    ...WEB_ANALYTICS_RECAP_DASHBOARD_PARAMS,
                    utm_content: cta,
                })
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadRecap()
        actions.recordOpened()
    }),
])
