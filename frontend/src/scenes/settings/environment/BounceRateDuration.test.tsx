import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { BounceRateDurationSetting } from './BounceRateDuration'

describe('<BounceRateDurationSetting />', () => {
    const loadTeam = (bounceRateDurationSeconds?: number): void => {
        act(() => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Admin,
                modifiers: bounceRateDurationSeconds === undefined ? {} : { bounceRateDurationSeconds },
            })
        })
    }

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('follows the stored duration when the team resolves after mount', () => {
        render(<BounceRateDurationSetting />)

        loadTeam(42)

        expect(screen.getByRole('spinbutton')).toHaveValue(42)
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('gates save when the team stores no duration', () => {
        render(<BounceRateDurationSetting />)

        loadTeam()

        expect(screen.getByRole('spinbutton')).toHaveValue(10)
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('keeps an edit that the input made before the team resolved', async () => {
        render(<BounceRateDurationSetting />)
        await userEvent.clear(screen.getByRole('spinbutton'))
        await userEvent.type(screen.getByRole('spinbutton'), '25')

        loadTeam(42)

        expect(screen.getByRole('spinbutton')).toHaveValue(25)
        expect(screen.getByText('Save').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
    })
})
