import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { StaleEventThreshold } from './StaleEventThreshold'

describe('<StaleEventThreshold />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the stored threshold when the team loads after the first render', () => {
        const { container } = render(<StaleEventThreshold />)
        const input = (): Element | null => container.querySelector('[data-attr="stale-event-threshold-days"]')
        expect(input()).toHaveValue(30)

        act(() => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                data_management_config: { stale_event_days: 7 },
            })
        })

        expect(input()).toHaveValue(7)
        // Save stays blocked, so a click cannot write the default over the stored value.
        expect(container.querySelector('[data-attr="stale-event-threshold-save"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })

    it('names the input, which the settings heading does not do for it', () => {
        const { container } = render(<StaleEventThreshold />)
        expect(container.querySelector('[data-attr="stale-event-threshold-days"]')).toHaveAccessibleName(
            'Stale event threshold in days'
        )
    })
})
