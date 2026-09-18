import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ErrorProjectUnavailable } from './ErrorProjectUnavailable'

const EMPTIED_ORGANIZATION = { ...MOCK_DEFAULT_ORGANIZATION, teams: [], projects: [] }

const DEPARTURE = {
    project_id: 997,
    project_name: 'Hedgebox',
    target_organization_id: '0182cb27-8dfc-0000-1f45-e8f0bcfcbd1a',
    target_organization_name: 'Hedgebox Inc.',
    target_organization_accessible: true,
    moved_at: '2024-05-06T12:00:00Z',
}

const NO_ACCESS_COPY = /You do not have access to any projects in this organization/

describe('ErrorProjectUnavailable', () => {
    afterEach(cleanup)

    // The lookup stays pending until `release` runs, so the in-flight state is assertable
    let release: (departures: (typeof DEPARTURE)[]) => void

    beforeEach(() => {
        const lookup = new Promise<(typeof DEPARTURE)[]>((resolve) => {
            release = resolve
        })
        useMocks({ get: { '/api/organizations/:organization_id/departed_projects/': () => lookup } })
    })

    function renderScene(): void {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, EMPTIED_ORGANIZATION)
        userLogic.mount()
        // No current team is what lands a member on this scene rather than on the access-removed copy
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, team: null, organization: EMPTIED_ORGANIZATION })
        render(
            <Provider>
                <ErrorProjectUnavailable />
            </Provider>
        )
    }

    it('does not claim no access while the departure lookup is in flight', async () => {
        renderScene()
        expect(screen.queryByText(NO_ACCESS_COPY)).not.toBeInTheDocument()

        release([DEPARTURE])
        await waitFor(() => expect(screen.getByText('Hedgebox moved to Hedgebox Inc.')).toBeInTheDocument())
        expect(screen.queryByText(NO_ACCESS_COPY)).not.toBeInTheDocument()
    })

    it('falls back to the no-access copy once the lookup comes back empty', async () => {
        renderScene()

        release([])
        await waitFor(() => expect(screen.getByText(NO_ACCESS_COPY)).toBeInTheDocument())
    })
})
