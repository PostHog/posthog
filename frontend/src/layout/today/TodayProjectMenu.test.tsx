import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { TodayProjectMenu } from './TodayProjectMenu'

describe('TodayProjectMenu', () => {
    afterEach(cleanup)

    it('lists projects on other instances and filters them by search', async () => {
        initKeaTests()
        newAccountMenuLogic.mount()
        await expectLogic(organizationLogic).toFinishAllListeners()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [{ ...MOCK_DEFAULT_TEAM, name: 'Project Alpha' }],
            external_project_links: [{ id: 'link-1', name: 'Alpha (EU)', url: 'https://eu.posthog.com/project/2' }],
        })
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        newAccountMenuLogic.actions.openProjectSwitcher()

        render(<TodayProjectMenu />)
        expect(screen.getByText('Other regions')).toBeInTheDocument()
        expect(screen.getByText('Alpha (EU)')).toBeInTheDocument()

        act(() => newAccountMenuLogic.actions.setProjectSearchValue('zzz'))
        expect(screen.queryByText('Other regions')).not.toBeInTheDocument()
        expect(screen.queryByText('Alpha (EU)')).not.toBeInTheDocument()
    })
})
