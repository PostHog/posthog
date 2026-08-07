import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TeamSettingToggle } from './TeamSettingToggle'

describe('<TeamSettingToggle />', () => {
    beforeEach(() => {
        useMocks({
            // Never resolves, so the toggle stays in its in-flight state for the assertion.
            patch: { [`/api/environments/${MOCK_DEFAULT_TEAM.id}`]: () => new Promise(() => {}) },
        })
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, anonymize_ips: false })
    })

    it('reflects the click immediately and shows a spinner while the save is in flight', async () => {
        const { container } = render(<TeamSettingToggle field="anonymize_ips" label="Discard client IP data" />)

        const toggle = screen.getByRole('switch')
        expect(toggle).toHaveAttribute('aria-checked', 'false')

        await userEvent.click(toggle)

        // Optimistic feedback: the switch flips before the server responds, and the per-toggle
        // spinner appears instead of silently doing nothing.
        expect(toggle).toHaveAttribute('aria-checked', 'true')
        expect(container.querySelector('.LemonSwitch--loading')).toBeInTheDocument()
    })
})
