import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { CookielessServerHashMode } from '~/types'

import { CookielessServerHashModeSetting } from './CookielessServerHashMode'

describe('<CookielessServerHashModeSetting />', () => {
    const loadTeam = (mode: CookielessServerHashMode): void => {
        act(() => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Admin,
                cookieless_server_hash_mode: mode,
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

    it('follows the stored value when the team resolves after mount', () => {
        render(<CookielessServerHashModeSetting />)
        expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')

        loadTeam(CookielessServerHashMode.Stateful)

        expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
        expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('keeps an edit that the toggle made before the team resolved', async () => {
        render(<CookielessServerHashModeSetting />)
        await userEvent.click(screen.getByRole('switch'))

        loadTeam(CookielessServerHashMode.Disabled)

        expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
        expect(screen.getByText('Save').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
    })
})
