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

    it('evaluates exception_autocapture requirement', () => {
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
})
