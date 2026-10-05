import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { WarehousePersonPropertiesSetting } from './WarehousePersonPropertiesSetting'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('lib/components/RestrictedArea', () => ({
    RestrictionScope: { Project: 'project' },
    useRestrictedArea: jest.fn(),
}))
jest.mock('lib/utils/accessControlUtils', () => ({ getAccessControlDisabledReason: jest.fn() }))
jest.mock('./CustomPropertyModal', () => ({ CustomPropertyModal: () => null }))

describe('WarehousePersonPropertiesSetting', () => {
    const openCreateModal = jest.fn()
    const propertyDefinition: CustomPropertyDefinitionApi = {
        id: 'definition-1',
        name: 'Plan tier',
        description: null,
        display_type: null,
        is_big_number: false,
        target_type: 'person',
        group_type_index: null,
        is_canonical: false,
        options: null,
        source: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
        has_workflow_reference: false,
    }

    beforeEach(() => {
        openCreateModal.mockClear()
        ;(useValues as jest.Mock).mockReturnValue({
            definitions: [propertyDefinition],
            definitionsInitialLoading: false,
            triggeringSourceIds: [],
            runsBySourceId: {},
            runsCountBySourceId: {},
            runsOffsetBySourceId: {},
            runsSearchBySourceId: {},
            runsLoadingBySourceId: {},
            runsLoadFailedBySourceId: {},
        })
        ;(useActions as jest.Mock).mockReturnValue({
            openCreateModal,
            openEditModal: jest.fn(),
            deleteDefinition: jest.fn(),
            triggerSync: jest.fn(),
            triggerBackfill: jest.fn(),
            setRunsSearch: jest.fn(),
            loadRuns: jest.fn(),
        })
        ;(useRestrictedArea as jest.Mock).mockImplementation(
            ({ minimumAccessLevel }: { minimumAccessLevel: TeamMembershipLevel }) =>
                minimumAccessLevel === TeamMembershipLevel.Admin ? 'Project admin access is required' : null
        )
        ;(getAccessControlDisabledReason as jest.Mock).mockReturnValue(null)
    })

    afterEach(cleanup)

    it('lets a project member add a person property', () => {
        render(<WarehousePersonPropertiesSetting />)

        const addButton = screen.getByRole('button', { name: 'Add person property' })
        expect(addButton).toBeEnabled()

        fireEvent.click(addButton)
        expect(openCreateModal).toHaveBeenCalledWith('person', true)
        expect(document.querySelector('[data-attr="delete-warehouse-profile-property"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        expect(useRestrictedArea).toHaveBeenCalledWith({
            scope: 'project',
            minimumAccessLevel: TeamMembershipLevel.Member,
        })
        expect(useRestrictedArea).toHaveBeenCalledWith({
            scope: 'project',
            minimumAccessLevel: TeamMembershipLevel.Admin,
        })
    })

    it('requires customer analytics editor access', () => {
        ;(getAccessControlDisabledReason as jest.Mock).mockReturnValue('Customer analytics editor access is required')

        render(<WarehousePersonPropertiesSetting />)

        expect(screen.getByRole('button', { name: 'Add person property' })).toHaveAttribute('aria-disabled', 'true')
    })
})
