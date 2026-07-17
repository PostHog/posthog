import { ErrorTrackingSettings, ErrorTrackingSettingsManager } from '~/common/utils/error-tracking-settings-manager'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

export interface LoadErrorTrackingSettingsInput {
    team: { id: number }
}

export type WithErrorTrackingSettings<T> = T & {
    errorTrackingSettings: ErrorTrackingSettings | null
}

export function createLoadErrorTrackingSettingsStep<T extends LoadErrorTrackingSettingsInput>(
    manager: ErrorTrackingSettingsManager | undefined
): ProcessingStep<T, WithErrorTrackingSettings<T>> {
    return async function loadErrorTrackingSettingsStep(input) {
        const errorTrackingSettings = manager ? await manager.getSettings(input.team.id) : null
        return ok({ ...input, errorTrackingSettings })
    }
}
