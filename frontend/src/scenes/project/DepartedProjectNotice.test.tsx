import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DepartedProjectNotice } from './DepartedProjectNotice'
import { departedProjectsLogic } from './departedProjectsLogic'

const DEPARTURE = {
    project_id: 997,
    project_name: 'Hedgebox',
    target_organization_id: '0182cb27-8dfc-0000-1f45-e8f0bcfcbd1a',
    target_organization_name: 'Hedgebox Inc.',
    target_organization_accessible: true,
    moved_at: '2024-05-06T12:00:00Z',
}

describe('DepartedProjectNotice', () => {
    afterEach(cleanup)

    function renderNotice(departures: (typeof DEPARTURE)[]): void {
        useMocks({ get: { '/api/organizations/:organization_id/departed_projects/': departures } })
        initKeaTests()
        organizationLogic.mount()
        render(
            <Provider>
                <DepartedProjectNotice />
            </Provider>
        )
    }

    it('names the project that left and where it went', async () => {
        renderNotice([DEPARTURE])
        await waitFor(() => expect(screen.getByText('Hedgebox moved to Hedgebox Inc.')).toBeInTheDocument())
        expect(screen.getAllByText('Open Hedgebox').length).toBeGreaterThan(0)
    })

    it('points at an admin of the other organization when the user cannot open the project', async () => {
        renderNotice([{ ...DEPARTURE, target_organization_accessible: false }])
        await waitFor(() => expect(screen.getByText(/ask an admin there for access/)).toBeInTheDocument())
        expect(screen.queryByText('Open Hedgebox')).not.toBeInTheDocument()
    })

    it('renders nothing when no project has left', async () => {
        renderNotice([])
        await expectLogic(departedProjectsLogic).toDispatchActions(['loadDepartedProjectsSuccess'])
        expect(screen.queryByText(/moved to/)).not.toBeInTheDocument()
    })
})
