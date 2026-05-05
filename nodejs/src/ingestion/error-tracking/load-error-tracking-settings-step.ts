import { ErrorTrackingSettings, ErrorTrackingSettingsManager } from '~/utils/error-tracking-settings-manager'

import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface LoadErrorTrackingSettingsInput {
    team: { id: number }
}

export type WithErrorTrackingSettings<T> = T & {
    errorTrackingSettings: ErrorTrackingSettings | null
}

export function createLoadErrorTrackingSettingsStep<T extends LoadErrorTrackingSettingsInput>(
    manager: ErrorTrackingSettingsManager
): ProcessingStep<T, WithErrorTrackingSettings<T>> {
    return async function loadErrorTrackingSettingsStep(input) {
        const errorTrackingSettings = await manager.getSettings(input.team.id)
        return ok({ ...input, errorTrackingSettings })
    }
}
