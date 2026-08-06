import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { dashboardTemplateChooserLogic } from './dashboardTemplateChooserLogic'
import type { DashboardTemplateTileLocation } from './dashboardTemplateChooserLogic'

/** Name of the official template that turns autocaptured events into charts. */
export const USER_INTERACTIONS_TEMPLATE_NAME = 'User interactions'

export interface SuggestedTemplateBannerProps {
    /** Matched against `template_name`. */
    templateName: string
    /** Where the suggestion was shown, reported on the template-clicked event. */
    tileLocation: DashboardTemplateTileLocation
    children: React.ReactNode
    dismissKey?: string
    className?: string
}

/**
 * Suggests one named dashboard template outside the chooser.
 *
 * Renders nothing when no template matches, because official templates are seeded by a
 * management command rather than on deploy, so the name can be absent in a given environment.
 */
export function SuggestedTemplateBanner({
    templateName,
    tileLocation,
    children,
    dismissKey,
    className,
}: SuggestedTemplateBannerProps): JSX.Element | null {
    // Keyed on scope and availability contexts, so this shares the chooser's instance and its
    // click flow, including the template-clicked event.
    const chooserLogic = dashboardTemplateChooserLogic({})
    const { allTemplates, isLoading } = useValues(chooserLogic)
    const { templateTileClicked } = useActions(chooserLogic)

    const template = useMemo(
        () => allTemplates.find((candidate) => candidate.template_name === templateName),
        [allTemplates, templateName]
    )

    if (!template) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className={className}
            dismissKey={dismissKey}
            action={{
                children: 'Create dashboard',
                onClick: () => templateTileClicked(template, tileLocation),
                loading: isLoading,
                disabledReason: isLoading ? 'Creating your dashboard' : undefined,
                'data-attr': 'create-dashboard-from-suggested-template',
            }}
        >
            {children}
        </LemonBanner>
    )
}
