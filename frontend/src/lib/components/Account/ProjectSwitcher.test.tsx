import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newAccountMenuLogic } from './newAccountMenuLogic'
import { ProjectSwitcher } from './ProjectSwitcher'

describe('ProjectSwitcher', () => {
    afterEach(cleanup)

    it.each([null, undefined, 'ungrouped'])(
        'shows grouping labels only when a named group exists (%s)',
        async (projectGroup) => {
            useMocks({
                get: {
                    '/api/organizations/:id/teams/data_freshness/': () => [
                        200,
                        { lookback_days: 30, quiet_after_days: 7, results: [] },
                    ],
                },
            })
            initKeaTests()
            newAccountMenuLogic.mount()
            await expectLogic(organizationLogic).toFinishAllListeners()
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                teams: [
                    { ...MOCK_DEFAULT_TEAM, name: 'Project Alpha', project_group: projectGroup },
                    { ...MOCK_DEFAULT_TEAM, id: 1001, project_id: 1001, name: 'Project Beta', project_group: null },
                ],
            })
            teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
            const errors = jest.spyOn(console, 'error').mockImplementation(() => {})

            try {
                render(<ProjectSwitcher />)
                if (projectGroup) {
                    expect(screen.getByText('Ungrouped')).toBeInTheDocument()
                    expect(screen.getByText('Other projects')).toBeInTheDocument()
                } else {
                    expect(screen.queryByText('Other projects')).not.toBeInTheDocument()
                }
                expect(screen.getByText('Project Alpha')).toBeInTheDocument()
                expect(screen.getByText('Project Beta')).toBeInTheDocument()

                await userEvent.type(screen.getByLabelText('Search projects'), 'Beta')
                expect(screen.queryByText('Project Alpha')).not.toBeInTheDocument()
                expect(screen.getByText('Project Beta')).toBeInTheDocument()
                if (projectGroup) {
                    expect(screen.getByText('Other projects')).toBeInTheDocument()
                }

                await userEvent.clear(screen.getByLabelText('Search projects'))
                expect(screen.getAllByText('Project Alpha')).toHaveLength(1)
                expect(screen.getAllByText('Project Beta')).toHaveLength(1)

                await userEvent.type(screen.getByLabelText('Search projects'), 'Alpha')
                act(() => newAccountMenuLogic.actions.setAccountMenuOpen(false))
                expect(screen.getAllByText('Project Beta')).toHaveLength(1)
                expect(errors.mock.calls.filter((call) => String(call[0]).includes('same key'))).toHaveLength(0)
            } finally {
                errors.mockRestore()
            }
        }
    )
})
