import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CustomPropertiesConfig } from './CustomPropertiesConfig'
import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn() } }))
jest.mock('lib/components/RestrictedArea', () => ({
    RestrictionScope: { Project: 'project' },
    useRestrictedArea: jest.fn(() => null),
}))
jest.mock('./CustomPropertyModal', () => ({ CustomPropertyModal: () => null }))

describe('CustomPropertiesConfig', () => {
    const open = LemonDialog.open as jest.Mock
    const deleteDefinition = jest.fn()
    const propertyDefinition: CustomPropertyDefinitionApi = {
        id: 'definition-1',
        name: 'ARR',
        description: null,
        display_type: 'currency',
        is_big_number: false,
        target_type: 'account',
        group_type_index: null,
        is_canonical: false,
        options: null,
        source: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
    }

    beforeEach(() => {
        open.mockClear()
        deleteDefinition.mockClear()
        ;(useValues as jest.Mock).mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return { featureFlags: {} }
            }
            if (logic === customPropertyDefinitionsLogic) {
                return {
                    filteredDefinitions: [propertyDefinition],
                    definitionsLoading: false,
                    searchTerm: '',
                    targetTypeFilter: 'all',
                    runsBySourceId: {},
                    runsCountBySourceId: {},
                    runsOffsetBySourceId: {},
                    runsSearchBySourceId: {},
                    runsLoadingBySourceId: {},
                    runsLoadFailedBySourceId: {},
                }
            }
            throw new Error('Unexpected logic')
        })
        ;(useActions as jest.Mock).mockReturnValue({
            openCreateModal: jest.fn(),
            openEditModal: jest.fn(),
            deleteDefinition,
            setSearchTerm: jest.fn(),
            setTargetTypeFilter: jest.fn(),
            setRunsSearch: jest.fn(),
            loadRuns: jest.fn(),
        })
    })

    afterEach(cleanup)

    it('opens a confirmation dialog before deleting a custom property', () => {
        render(<CustomPropertiesConfig />)

        const deleteButton = document.querySelector('[data-attr="delete-custom-property"]')
        expect(deleteButton).toBeInTheDocument()
        fireEvent.click(deleteButton as HTMLElement)

        expect(open).toHaveBeenCalledTimes(1)
        const dialog = open.mock.calls[0][0]
        const { container } = render(dialog.description)
        expect(container).toHaveTextContent('This action is irreversible.')
        expect(container).toHaveTextContent('All stored values for this custom property will be permanently deleted.')
        expect(deleteDefinition).not.toHaveBeenCalled()

        dialog.primaryButton.onClick()
        expect(deleteDefinition).toHaveBeenCalledWith({ id: propertyDefinition.id })
    })
})
