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

function setup(projectCreationForbiddenReason: string | null): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === preflightLogic) {
            return { preflight: { can_create_org: false } }
        }
        if (logic === organizationLogic) {
            return { currentOrganization: { teams: [] }, projectCreationForbiddenReason }
        }
        if (logic === teamLogic) {
            return { currentTeam: MOCK_DEFAULT_TEAM }
        }
        if (logic === upgradeModalLogic) {
            return { guardAvailableFeature: jest.fn() }
        }
        if (logic === pendingInvitesLogic) {
            return { pendingInvites: [] }
        }
        return {}
    })
    mockedUseActions.mockImplementation((logic: unknown) => {
        if (logic === globalModalsLogic) {
            return { showCreateProjectModal: jest.fn() }
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
        [null, false],
        ['Self-hosted PostHog supports one project. See PostHog Cloud plans for more projects.', true],
        ['You need to be an organization admin or above to create new projects.', true],
    ])('switcher with forbidden reason %s is disabled: %s', (reason, disabled) => {
        setup(reason)

        render(<ProjectSwitcher dialog={false} />)

        const button = screen.getByText('New project').closest('button')
        expect(button).not.toBeNull()
        if (disabled) {
            expect(button).toBeDisabled()
        } else {
            expect(button).toBeEnabled()
        }
    })

    test('legacy project menu disables creation at the self-hosted limit', () => {
        setup('Self-hosted PostHog supports one project. See PostHog Cloud plans for more projects.')

        render(<ProjectCombobox />)

        expect(screen.getByText('New project').closest('button')).toBeDisabled()
    })
})
