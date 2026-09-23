import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, render, screen } from '@testing-library/react'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { type AppContext } from '~/types'

import { ErrorProjectUnavailable } from './ErrorProjectUnavailable'

// The current project is one the user cannot open, so it is absent from `organization.teams`.
const unavailableTeam = { ...MOCK_DEFAULT_TEAM, id: 999 }

describe('ErrorProjectUnavailable', () => {
    afterEach(cleanup)

    test.each([
        ['some', [MOCK_DEFAULT_TEAM], "You don't have access to this project", true],
        ['no', [], `Welcome to ${MOCK_DEFAULT_ORGANIZATION.name} on PostHog`, false],
    ])(
        'with %s other projects the user can open, describes the state without claiming access was removed',
        (_, teams, heading, canSwitch) => {
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                current_user: {
                    ...MOCK_DEFAULT_USER,
                    team: unavailableTeam,
                    organization: { ...MOCK_DEFAULT_ORGANIZATION, teams },
                },
            } as AppContext
            initKeaTests()
            userLogic.mount()

            render(<ErrorProjectUnavailable />)

            expect(screen.getByText(heading)).toBeTruthy()
            expect(screen.queryByText(/access has been removed/)).toBeNull()
            expect(screen.queryByText(/switch to a project you have access to/) !== null).toBe(canSwitch)
        }
    )
})
