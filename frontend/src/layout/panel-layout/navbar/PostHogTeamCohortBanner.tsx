import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { IconCohort } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { postHogTeamCohortBannerLogic } from './postHogTeamCohortBannerLogic'

export function PostHogTeamCohortBanner({ isCollapsed }: { isCollapsed: boolean }): JSX.Element | null {
    const { bannerVisible } = useValues(postHogTeamCohortBannerLogic)
    const { dismissBanner, rejoinPostHogTeamCohort } = useActions(postHogTeamCohortBannerLogic)

    if (!bannerVisible) {
        return null
    }

    if (isCollapsed) {
        return (
            <ButtonPrimitive
                iconOnly
                aria-label="Rejoin the PostHog Team cohort"
                tooltip="You're out of the PostHog Team cohort. Click to rejoin."
                tooltipPlacement="right"
                onClick={() => rejoinPostHogTeamCohort(true)}
                data-attr="nav-posthog-team-cohort-rejoin"
            >
                <IconCohort className="text-warning" />
            </ButtonPrimitive>
        )
    }

    return (
        <div className="mb-2 flex w-full flex-col gap-1 rounded border border-l-4 border-l-warning bg-primary py-1 pl-2 pr-0.5 text-xs">
            <div className="flex items-start justify-between gap-1">
                <div className="flex min-w-0 items-start gap-1 pt-0.5">
                    <IconCohort className="mt-px shrink-0 text-sm text-warning" />
                    <span className="min-w-0 font-semibold">You're out of the PostHog Team cohort</span>
                </div>
                <LemonButton
                    icon={<IconX />}
                    tooltip="Dismiss"
                    tooltipPlacement="right"
                    size="xsmall"
                    onClick={dismissBanner}
                    data-attr="nav-posthog-team-cohort-banner-dismiss"
                />
            </div>
            <p className="mb-0 pr-1.5 text-secondary">Flags that target it are off for you.</p>
            <LemonButton
                type="secondary"
                size="xsmall"
                className="mb-1 mr-1.5"
                onClick={() => rejoinPostHogTeamCohort(false)}
                data-attr="nav-posthog-team-cohort-rejoin"
            >
                Rejoin cohort
            </LemonButton>
        </div>
    )
}
