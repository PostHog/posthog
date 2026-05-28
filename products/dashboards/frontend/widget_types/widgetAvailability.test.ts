import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { WidgetAvailabilityConfig } from './widgetAvailability'
import { getWidgetAvailabilityStatus, isWidgetAvailabilityRequirementMet } from './widgetAvailability'

describe('widgetAvailability', () => {
    it('treats widgets without availability config as available', () => {
        expect(getWidgetAvailabilityStatus(undefined, MOCK_DEFAULT_TEAM)).toEqual({
            isAvailable: true,
            config: undefined,
        })
    })

    it.each([
        {
            requirement: 'exception_autocapture' as const,
            teamPropKey: 'autocapture_exceptions_opt_in' as const,
            unavailableTitle: "You haven't captured any exceptions",
            unavailableReason: 'Enable exception autocapture to get started.',
            setupActionLabel: 'Enable exception autocapture',
        },
        {
            requirement: 'session_replay_enabled' as const,
            teamPropKey: 'session_recording_opt_in' as const,
            unavailableTitle: 'Session replay is not enabled',
            unavailableReason: 'Turn on session recordings for this project.',
            setupActionLabel: 'Enable session replay',
        },
    ])(
        'evaluates $requirement requirement',
        ({ requirement, teamPropKey, unavailableTitle, unavailableReason, setupActionLabel }) => {
            const availability: WidgetAvailabilityConfig = {
                requirement,
                unavailableTitle,
                unavailableReason,
                setupActionLabel,
            }

            expect(
                isWidgetAvailabilityRequirementMet(requirement, {
                    ...MOCK_DEFAULT_TEAM,
                    [teamPropKey]: false,
                })
            ).toBe(false)

            expect(
                isWidgetAvailabilityRequirementMet(requirement, {
                    ...MOCK_DEFAULT_TEAM,
                    [teamPropKey]: true,
                })
            ).toBe(true)

            expect(
                getWidgetAvailabilityStatus(availability, {
                    ...MOCK_DEFAULT_TEAM,
                    [teamPropKey]: false,
                }).isAvailable
            ).toBe(false)
        }
    )
})
