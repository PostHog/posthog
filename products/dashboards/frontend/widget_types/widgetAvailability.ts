import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

/** New catalog-driven setup requirements: add here — CONTRIBUTING.md */
export type WidgetAvailabilityRequirementId = 'exception_autocapture' | 'session_replay_enabled'

export type WidgetAvailabilityConfig = {
    /** Stable id evaluated by `widgetAvailability` helpers. */
    requirement: WidgetAvailabilityRequirementId
    /** Title shown in setup prompts when the requirement is unmet. */
    unavailableTitle: string
    /** Body copy shown in setup prompts when the requirement is unmet. */
    unavailableReason: string
    /** Primary setup CTA label. */
    setupActionLabel: string
    /** Optional docs link for a secondary CTA. */
    docsHref?: string
}

export type WidgetAvailabilityStatus = {
    isAvailable: boolean
    config: WidgetAvailabilityConfig | undefined
}

export function isWidgetAvailabilityRequirementMet(
    requirement: WidgetAvailabilityRequirementId,
    team: TeamType | null
): boolean {
    switch (requirement) {
        // New requirements: add a case here — CONTRIBUTING.md
        case 'exception_autocapture':
            return !!team?.autocapture_exceptions_opt_in
        case 'session_replay_enabled':
            return !!team?.session_recording_opt_in
        default: {
            const _exhaustive: never = requirement
            return _exhaustive
        }
    }
}

export function getWidgetAvailabilityStatus(
    config: WidgetAvailabilityConfig | undefined,
    team: TeamType | null
): WidgetAvailabilityStatus {
    if (!config) {
        return { isAvailable: true, config: undefined }
    }

    return {
        isAvailable: isWidgetAvailabilityRequirementMet(config.requirement, team),
        config,
    }
}

export function useWidgetAvailability(config: WidgetAvailabilityConfig | undefined): WidgetAvailabilityStatus {
    const { currentTeam } = useValues(teamLogic)
    return getWidgetAvailabilityStatus(config, currentTeam)
}
