import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { globalModalsLogic } from '~/layout/globalModalsLogic'

import { newAccountMenuLogic } from './newAccountMenuLogic'
import { pendingInvitesLogic } from './pendingInvitesLogic'
import { ProjectCombobox } from './ProjectCombobox'
import { ProjectSwitcher } from './ProjectSwitcher'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

const mockedUseActions = useActions as jest.Mock
const mockedUseValues = useValues as jest.Mock
const guardAvailableFeature = jest.fn()
const showCreateProjectModal = jest.fn()

function setup(isHobby: boolean): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === preflightLogic) {
            return { preflight: { can_create_org: !isHobby }, isHobby }
        }
        if (logic === organizationLogic) {
            return { currentOrganization: { teams: [] }, projectCreationForbiddenReason: null }
        }
        if (logic === teamLogic) {
            return { currentTeam: MOCK_DEFAULT_TEAM }
        }
        if (logic === upgradeModalLogic) {
            return { guardAvailableFeature }
        }
        if (logic === pendingInvitesLogic) {
            return { pendingInvites: [] }
        }
        return {}
    })
    mockedUseActions.mockImplementation((logic: unknown) => {
        if (logic === globalModalsLogic) {
            return { showCreateProjectModal }
        }
        if (logic === newAccountMenuLogic) {
            return { closeProjectSwitcher: jest.fn(), setAccountMenuOpen: jest.fn() }
        }
        return {}
    })
}

describe('project creation controls', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    test.each([
        ['switcher', ProjectSwitcher],
        ['legacy menu', ProjectCombobox],
    ])('%s hides project creation on Hobby', (_name, Component) => {
        setup(true)

        render(<Component />)

        expect(screen.queryByText('New project')).not.toBeInTheDocument()
    })

    test.each([
        ['switcher', ProjectSwitcher],
        ['legacy menu', ProjectCombobox],
    ])('%s keeps project creation on Cloud', (_name, Component) => {
        setup(false)

        render(<Component />)

        expect(screen.getByText('New project')).toBeInTheDocument()
    })
})
