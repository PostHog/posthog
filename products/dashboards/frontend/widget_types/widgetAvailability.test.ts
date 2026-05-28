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

    it('evaluates exception_autocapture requirement from catalog-shaped config', () => {
        const availability: WidgetAvailabilityConfig = {
            requirement: 'exception_autocapture',
            unavailableTitle: "You haven't captured any exceptions",
            unavailableReason: 'Enable exception autocapture to get started.',
            setupActionLabel: 'Enable exception autocapture',
        }

        expect(
            isWidgetAvailabilityRequirementMet('exception_autocapture', {
                ...MOCK_DEFAULT_TEAM,
                autocapture_exceptions_opt_in: false,
            })
        ).toBe(false)

        expect(
            isWidgetAvailabilityRequirementMet('exception_autocapture', {
                ...MOCK_DEFAULT_TEAM,
                autocapture_exceptions_opt_in: true,
            })
        ).toBe(true)

        expect(
            getWidgetAvailabilityStatus(availability, {
                ...MOCK_DEFAULT_TEAM,
                autocapture_exceptions_opt_in: false,
            }).isAvailable
        ).toBe(false)
    })

    it('evaluates session_replay_enabled requirement from team session_recording_opt_in', () => {
        const availability: WidgetAvailabilityConfig = {
            requirement: 'session_replay_enabled',
            unavailableTitle: 'Session replay is not enabled',
            unavailableReason: 'Turn on session recordings for this project.',
            setupActionLabel: 'Enable session replay',
        }

        expect(
            isWidgetAvailabilityRequirementMet('session_replay_enabled', {
                ...MOCK_DEFAULT_TEAM,
                session_recording_opt_in: false,
            })
        ).toBe(false)

        expect(
            isWidgetAvailabilityRequirementMet('session_replay_enabled', {
                ...MOCK_DEFAULT_TEAM,
                session_recording_opt_in: true,
            })
        ).toBe(true)

        expect(
            getWidgetAvailabilityStatus(availability, {
                ...MOCK_DEFAULT_TEAM,
                session_recording_opt_in: false,
            }).isAvailable
        ).toBe(false)
    })
})
