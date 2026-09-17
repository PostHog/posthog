import posthog from 'posthog-js'

import * as superheroPng from '@posthog/brand/hoggies/png/superhero'
import { IconOpenSidebar } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

const HedgehogSuperhero = pngHoggie(superheroPng)

type SupportActivationButtonProps = {
    source: 'support_empty_state' | 'dashboard_widget'
    className?: string
    widgetType?: string
    widgetId?: string
    dashboardId?: number | null
    onClick?: () => void
}

export function SupportActivationButton({
    source,
    className,
    widgetType,
    widgetId,
    dashboardId,
    onClick,
}: SupportActivationButtonProps): JSX.Element {
    return (
        <LemonButton
            className={className ?? 'hidden @md:flex'}
            type="primary"
            to={urls.supportSettings()}
            onClick={() => {
                sessionStorage.setItem(
                    'support_activation_source',
                    JSON.stringify({ source, widget_type: widgetType, widget_id: widgetId, dashboard_id: dashboardId })
                )
                posthog.capture('support activation started', {
                    source,
                    widget_type: widgetType,
                    widget_id: widgetId,
                    dashboard_id: dashboardId,
                })
                onClick?.()
            }}
        >
            Enable
        </LemonButton>
    )
}

export function ConversationsDisabledBanner(): JSX.Element {
    return (
        <LemonBanner type="info" hideIcon={true}>
            <div className="flex gap-8 p-8 lg:flex-row justify-center flex-wrap">
                <div className="hidden lg:flex justify-center items-center w-full lg:w-50">
                    <HedgehogSuperhero className="h-[200px] w-[200px]" />
                </div>
                <div className="flex flex-col gap-2 flex-shrink max-w-180">
                    <h2 className="text-lg font-semibold">Welcome to Support</h2>
                    <p className="font-normal">
                        Support lets you manage customer conversations directly inside PostHog. Enable the conversations
                        API to get started.
                    </p>
                    <ul className="list-disc list-inside font-normal space-y-2">
                        <li>
                            <strong>Centralized inbox:</strong> Receive and reply to customer messages from an in-app
                            widget, Slack, Email or the API — all in one place.
                        </li>
                        <li>
                            <strong>Ticket management:</strong> Track, prioritize, and assign tickets with SLAs so
                            nothing falls through the cracks.
                        </li>
                        <li>
                            <strong>Deep product context:</strong> See session recordings, events, error tracking, and
                            previous tickets for each person behind every ticket.
                        </li>
                        <li>
                            <strong>Workflow automation:</strong> Trigger workflows on ticket events like creation,
                            status changes, or new messages to automate assignments, notifications, and more.
                        </li>
                    </ul>
                    <div className="flex items-center gap-x-4 gap-y-2 flex-wrap">
                        <SupportActivationButton source="support_empty_state" />
                        <LemonButton
                            type="tertiary"
                            sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                            to="https://posthog.com/docs/support?utm_medium=in-product&utm_campaign=support-empty-state-docs-link"
                            data-attr="support-introduction-docs-link"
                            targetBlank
                        >
                            Learn more
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}
