import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { TimezoneConfig } from './TimezoneConfig'

describe('<TimezoneConfig />', () => {
    beforeEach(async () => {
        initKeaTests()
        teamLogic.mount()
        preflightLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            timezone: 'Europe/Madrid',
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        await expectLogic(preflightLogic).toFinishAllListeners()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the current time zone when the selection is cleared with backspace', async () => {
        const { container } = render(<TimezoneConfig />)
        const input = container.querySelector('input[type="text"]') as HTMLInputElement

        await userEvent.click(input)
        await userEvent.keyboard('{Backspace}')

        expect(screen.getByText('Europe / Madrid (UTC+1:00)')).toBeInTheDocument()
        await expectLogic(teamLogic).toNotHaveDispatchedActions(['updateCurrentTeam'])
    })
})
