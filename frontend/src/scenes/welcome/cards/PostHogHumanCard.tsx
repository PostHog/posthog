import { useActions, useValues } from 'kea'

import { IconArrowRight, IconHeadset } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function PostHogHumanCard(): JSX.Element | null {
    const { posthogContact, sharedSlackChannelUrl } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (!posthogContact && !sharedSlackChannelUrl) {
        return null
    }

    const subtitle = posthogContact ? `${posthogContact.name} can help if you get stuck.` : null

    return (
        <LemonCard hoverEffect={false} className="p-4" data-attr="welcome-posthog-human-card">
            <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--color-brand-yellow)]/15 flex items-center justify-center text-[var(--color-brand-yellow)]">
                    <IconHeadset className="text-xl" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold">Your PostHog human</div>
                    {subtitle ? <div className="text-xs text-muted">{subtitle}</div> : null}
                </div>
                {sharedSlackChannelUrl ? (
                    <Link
                        to={sharedSlackChannelUrl}
                        target="_blank"
                        targetBlankIcon={false}
                        subtle
                        onClick={() => trackCardClick('contact', sharedSlackChannelUrl)}
                        data-attr="welcome-posthog-human-slack-cta"
                        className="inline-flex items-center gap-1 text-xs text-muted flex-shrink-0"
                    >
                        <span>Join your shared Slack channel</span>
                        <IconArrowRight />
                    </Link>
                ) : null}
            </div>
        </LemonCard>
    )
}
