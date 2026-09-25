/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { DepartedProjectApi } from 'products/platform_features/frontend/generated/api.schemas'

import { DepartedProjectNotice } from './DepartedProjectNotice'
import { departedProjectsLogic } from './departedProjectsLogic'

const DEPARTURE: DepartedProjectApi = {
    project_id: 997,
    project_name: 'Hedgebox',
    target_organization_id: '0182cb27-8dfc-0000-1f45-e8f0bcfcbd1a',
    target_organization_name: 'Hedgebox Inc.',
    target_project_accessible: true,
    moved_at: '2024-05-06T12:00:00Z',
}

describe('DepartedProjectNotice', () => {
    afterEach(cleanup)

    function renderNotice(
        departures: DepartedProjectApi[],
        level: OrganizationMembershipLevel = OrganizationMembershipLevel.Admin
    ): jest.Mock {
        const lookup = jest.fn(() => departures)
        useMocks({ get: { '/api/organizations/:organization_id/departed_projects/': lookup } })
        initKeaTests(true, undefined, undefined, { ...MOCK_DEFAULT_ORGANIZATION, membership_level: level })
        organizationLogic.mount()
        render(
            <Provider>
                <DepartedProjectNotice />
            </Provider>
        )
        return lookup
    }

    it('names the project that left and where it went', async () => {
        renderNotice([DEPARTURE])
        await waitFor(() => expect(screen.getByText('Hedgebox moved to Hedgebox Inc.')).toBeInTheDocument())
        expect(screen.getAllByText('Open Hedgebox').length).toBeGreaterThan(0)
    })

    it('points at an admin of the other organization when the project is not open to the user there', async () => {
        renderNotice([{ ...DEPARTURE, target_project_accessible: false }])
        await waitFor(() => expect(screen.getByText(/Ask an admin of Hedgebox Inc\. for access/)).toBeInTheDocument())
        expect(screen.queryByText('Open Hedgebox')).not.toBeInTheDocument()
    })

    it('describes the destination without naming it when the user cannot reach it', async () => {
        renderNotice([
            {
                ...DEPARTURE,
                target_organization_id: null,
                target_organization_name: null,
                target_project_accessible: false,
            },
        ])
        await waitFor(() => expect(screen.getByText('Hedgebox moved to another organization')).toBeInTheDocument())
        expect(screen.getByText(/Ask an admin of the organization it moved to for access/)).toBeInTheDocument()
        expect(screen.queryByText('Open Hedgebox')).not.toBeInTheDocument()
    })

    it('renders nothing when no project has left', async () => {
        renderNotice([])
        await expectLogic(departedProjectsLogic).toDispatchActions(['loadDepartedProjectsSuccess'])
        expect(screen.queryByText(/moved to/)).not.toBeInTheDocument()
    })

    it('does not ask for departures a plain member is not allowed to read', async () => {
        const lookup = renderNotice([DEPARTURE], OrganizationMembershipLevel.Member)
        await expectLogic(organizationLogic).toFinishAllListeners()
        expect(lookup).not.toHaveBeenCalled()
        expect(screen.queryByText(/moved to/)).not.toBeInTheDocument()
    })
})
