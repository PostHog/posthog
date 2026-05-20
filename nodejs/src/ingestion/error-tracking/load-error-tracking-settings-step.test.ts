import { ErrorTrackingSettingsManager } from '~/utils/error-tracking-settings-manager'

import { isOkResult } from '../pipelines/results'
import { createLoadErrorTrackingSettingsStep } from './load-error-tracking-settings-step'

describe('createLoadErrorTrackingSettingsStep', () => {
    const buildManager = (
        settingsByTeam: Record<
            string,
            { projectRateLimitValue: number | null; projectRateLimitBucketSizeMinutes: number | null } | null
        >
    ): jest.Mocked<Pick<ErrorTrackingSettingsManager, 'getSettings'>> => ({
        getSettings: jest.fn((teamId: number) => Promise.resolve(settingsByTeam[String(teamId)] ?? null)),
    })

    it('attaches null when the team has no settings row', async () => {
        const manager = buildManager({ '1': null })
        const step = createLoadErrorTrackingSettingsStep(manager as unknown as ErrorTrackingSettingsManager)

        const result = await step({ team: { id: 1 } })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.errorTrackingSettings).toBeNull()
        }
    })

    it('attaches the loaded settings', async () => {
        const manager = buildManager({
            '1': { projectRateLimitValue: 100, projectRateLimitBucketSizeMinutes: 5 },
        })
        const step = createLoadErrorTrackingSettingsStep(manager as unknown as ErrorTrackingSettingsManager)

        const result = await step({ team: { id: 1 } })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.errorTrackingSettings).toEqual({
                projectRateLimitValue: 100,
                projectRateLimitBucketSizeMinutes: 5,
            })
        }
    })

    it('attaches null without calling the manager when no manager is provided', async () => {
        const step = createLoadErrorTrackingSettingsStep<{ team: { id: number } }>(undefined)

        const result = await step({ team: { id: 1 } })

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.errorTrackingSettings).toBeNull()
        }
    })
})
