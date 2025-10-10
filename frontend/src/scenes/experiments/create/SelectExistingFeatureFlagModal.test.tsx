import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { SelectExistingFeatureFlagModal } from './SelectExistingFeatureFlagModal'
import { selectExistingFeatureFlagModalLogic } from './selectExistingFeatureFlagModalLogic'

describe('SelectExistingFeatureFlagModal', () => {
    const mockOnClose = jest.fn()
    const mockOnSelect = jest.fn()
    let logic: ReturnType<typeof selectExistingFeatureFlagModalLogic.build>

    const baseFeatureFlag: FeatureFlagType = {
        id: 1,
        key: 'test-flag',
        name: 'Test Flag',
        filters: {
            groups: [],
            payloads: {},
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
        created_at: '2021-01-01',
        updated_at: '2021-01-01',
        created_by: null,
        is_simple_flag: false,
        is_remote_configuration: false,
        deleted: false,
        active: true,
        rollout_percentage: null,
        experiment_set: null,
        features: null,
        surveys: null,
        rollback_conditions: [],
        performed_rollback: false,
        can_edit: true,
        tags: [],
        ensure_experience_continuity: null,
        user_access_level: AccessControlLevel.Admin,
        status: 'ACTIVE',
        has_encrypted_payloads: false,
        version: 0,
        last_modified_by: null,
        evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
        evaluation_tags: [],
    }

    const mockFeatureFlags: FeatureFlagType[] = [
        baseFeatureFlag,
        {
            ...baseFeatureFlag,
            id: 2,
            key: 'another-flag',
            name: 'Another Flag',
            filters: {
                ...baseFeatureFlag.filters,
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'variant-1', rollout_percentage: 33 },
                        { key: 'variant-2', rollout_percentage: 34 },
                    ],
                },
            },
        },
    ]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/feature_flags/': () => [
                    200,
                    {
                        results: mockFeatureFlags,
                        count: mockFeatureFlags.length,
                    },
                ],
            },
        })
        initKeaTests()
        logic = selectExistingFeatureFlagModalLogic()
        logic.mount()
        logic.actions.openSelectExistingFeatureFlagModal()
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    describe('basic rendering', () => {
        it('renders modal with title and description', () => {
            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            expect(screen.getByText('Choose an existing feature flag')).toBeInTheDocument()
            expect(screen.getByText(/Select an existing multivariate feature flag/)).toBeInTheDocument()
        })

        it('renders search filter', () => {
            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            expect(screen.getByPlaceholderText('Search for feature flags')).toBeInTheDocument()
        })

        it('renders table columns', () => {
            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            expect(screen.getByText('Key')).toBeInTheDocument()
            expect(screen.getByText('Name')).toBeInTheDocument()
        })
    })

    describe('interactions', () => {
        it('calls onSelect and onClose when Select button is clicked', async () => {
            const resetFiltersSpy = jest.spyOn(logic.actions, 'resetFilters')

            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            const selectButtons = await screen.findAllByRole('button', { name: 'Select' })
            await userEvent.click(selectButtons[0])

            expect(mockOnSelect).toHaveBeenCalledWith(mockFeatureFlags[0])
            expect(resetFiltersSpy).toHaveBeenCalled()
            expect(mockOnClose).toHaveBeenCalled()

            resetFiltersSpy.mockRestore()
        })

        it('calls resetFilters and onClose when modal is closed', async () => {
            const resetFiltersSpy = jest.spyOn(logic.actions, 'resetFilters')

            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            const closeButton = screen.getByRole('button', { name: /close/i })
            await userEvent.click(closeButton)

            expect(resetFiltersSpy).toHaveBeenCalled()
            expect(mockOnClose).toHaveBeenCalled()

            resetFiltersSpy.mockRestore()
        })

        it('calls setFilters when sorting is changed', async () => {
            const setFiltersSpy = jest.spyOn(logic.actions, 'setFilters')

            render(<SelectExistingFeatureFlagModal onClose={mockOnClose} onSelect={mockOnSelect} />)

            const keyHeader = await screen.findByText('Key')
            await userEvent.click(keyHeader)

            expect(setFiltersSpy).toHaveBeenCalledWith({
                order: 'key',
                page: 1,
            })

            setFiltersSpy.mockRestore()
        })
    })
})
