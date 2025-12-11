import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AccessControlLevel, FeatureFlagEvaluationRuntime, FeatureFlagType } from '~/types'

import { VariantsPanelLinkFeatureFlag } from './VariantsPanelLinkFeatureFlag'

describe('VariantsPanelLinkFeatureFlag', () => {
    const mockSetShowFeatureFlagSelector = jest.fn()

    const baseFeatureFlag: FeatureFlagType = {
        id: 1,
        key: 'test-experiment-flag',
        name: 'Test Experiment Feature Flag',
        filters: {
            groups: [
                {
                    properties: [],
                    rollout_percentage: 100,
                },
            ],
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

    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    describe('empty state', () => {
        it('renders empty state when no feature flag is selected', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={null}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('No feature flag selected')).toBeInTheDocument()
            expect(
                screen.getByText('Select an existing multivariate feature flag to use with this experiment')
            ).toBeInTheDocument()
        })

        it('renders Select Feature Flag button in empty state', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={null}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const selectButton = screen.getByRole('button', { name: 'Select Feature Flag' })
            expect(selectButton).toBeInTheDocument()
        })

        it('calls setShowFeatureFlagSelector when Select button is clicked', async () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={null}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const selectButton = screen.getByRole('button', { name: 'Select Feature Flag' })
            await userEvent.click(selectButton)

            expect(mockSetShowFeatureFlagSelector).toHaveBeenCalledTimes(1)
        })
    })

    describe('with linked feature flag', () => {
        it('renders feature flag key and name', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('test-experiment-flag')).toBeInTheDocument()
            expect(screen.getByText('Test Experiment Feature Flag')).toBeInTheDocument()
        })

        it('renders external link to feature flag', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const link = screen.getByRole('link', { name: /view feature flag/i })
            expect(link).toHaveAttribute('href', '/feature_flags/1')
            expect(link).toHaveAttribute('target', '_blank')
        })

        it('renders Change button', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const changeButton = screen.getByRole('button', { name: 'Change' })
            expect(changeButton).toBeInTheDocument()
        })

        it('calls setShowFeatureFlagSelector when Change button is clicked', async () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const changeButton = screen.getByRole('button', { name: 'Change' })
            await userEvent.click(changeButton)

            expect(mockSetShowFeatureFlagSelector).toHaveBeenCalledTimes(1)
        })

        it('renders active status for active flag', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={{ ...baseFeatureFlag, active: true }}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('Active')).toBeInTheDocument()
            const statusDot = screen.getByTitle('Active')
            expect(statusDot).toHaveClass('bg-success')
        })

        it('renders inactive status for inactive flag', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={{ ...baseFeatureFlag, active: false }}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('Inactive')).toBeInTheDocument()
            const statusDot = screen.getByTitle('Inactive')
            expect(statusDot).toHaveClass('bg-muted')
        })

        it('does not render description when name is not set', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={{ ...baseFeatureFlag, name: '' }}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.queryByText('Test Experiment Feature Flag')).not.toBeInTheDocument()
        })
    })

    describe('variants display', () => {
        it('renders all variants', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('control')).toBeInTheDocument()
            expect(screen.getByText('test')).toBeInTheDocument()
        })

        it('highlights control variant with primary tag', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const controlTag = screen.getByText('control').closest('.LemonTag')
            expect(controlTag).toHaveClass('LemonTag--primary')
        })

        it('renders multiple variants', () => {
            const flagWithMultipleVariants: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 25 },
                            { key: 'variant-1', rollout_percentage: 25 },
                            { key: 'variant-2', rollout_percentage: 25 },
                            { key: 'variant-3', rollout_percentage: 25 },
                        ],
                    },
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithMultipleVariants}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('control')).toBeInTheDocument()
            expect(screen.getByText('variant-1')).toBeInTheDocument()
            expect(screen.getByText('variant-2')).toBeInTheDocument()
            expect(screen.getByText('variant-3')).toBeInTheDocument()
        })

        it('handles empty variants array gracefully', () => {
            const flagWithoutVariants: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    multivariate: undefined,
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithoutVariants}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.queryByText('control')).not.toBeInTheDocument()
        })
    })

    describe('targeting summary', () => {
        it('renders targeting section', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('Targeting')).toBeInTheDocument()
        })

        it('shows "All users" for groups with no properties', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('100% of all users')).toBeInTheDocument()
        })

        it('shows rollout percentage for groups', () => {
            const flagWithRollout: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 50,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithRollout}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('50% of all users')).toBeInTheDocument()
        })

        it('shows property conditions count', () => {
            const flagWithProperties: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', value: 'test@example.com', type: 'person', operator: 'exact' },
                                { key: 'country', value: 'US', type: 'person', operator: 'exact' },
                            ] as any,
                            rollout_percentage: 100,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithProperties}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('100% of users matching 2 conditions')).toBeInTheDocument()
        })

        it('shows singular "condition" for one property', () => {
            const flagWithOneProperty: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', value: 'test@example.com', type: 'person', operator: 'exact' },
                            ] as any,
                            rollout_percentage: 100,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithOneProperty}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('100% of users matching 1 condition')).toBeInTheDocument()
        })

        it('shows variant targeting when specified', () => {
            const flagWithVariantTargeting: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: 100,
                            variant: 'test',
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithVariantTargeting}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText(/all users → variant "test"/)).toBeInTheDocument()
        })

        it('shows "All users" when groups is empty', () => {
            const flagWithEmptyGroups: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithEmptyGroups}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('All users')).toBeInTheDocument()
        })

        it('handles simple flag with rollout percentage', () => {
            const simpleFlag: FeatureFlagType = {
                ...baseFeatureFlag,
                is_simple_flag: true,
                rollout_percentage: 75,
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={simpleFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('75% of all users')).toBeInTheDocument()
        })
    })

    describe('targeting summary expansion', () => {
        it('shows first 2 conditions when there are more than 2', () => {
            const flagWithManyGroups: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        { properties: [], rollout_percentage: 25 },
                        { properties: [], rollout_percentage: 50 },
                        { properties: [], rollout_percentage: 75 },
                        { properties: [], rollout_percentage: 100 },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithManyGroups}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('25% of all users')).toBeInTheDocument()
            expect(screen.getByText('50% of all users')).toBeInTheDocument()
            expect(screen.getByText('+2 more conditions')).toBeInTheDocument()
        })

        it('shows "+1 more condition" when there are exactly 3 conditions', () => {
            const flagWithThreeGroups: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        { properties: [], rollout_percentage: 33 },
                        { properties: [], rollout_percentage: 33 },
                        { properties: [], rollout_percentage: 34 },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithThreeGroups}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('+1 more condition')).toBeInTheDocument()
        })

        it('expands to show all conditions when expand button is clicked', async () => {
            const flagWithManyGroups: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        { properties: [], rollout_percentage: 25 },
                        { properties: [], rollout_percentage: 50 },
                        { properties: [], rollout_percentage: 75 },
                        { properties: [], rollout_percentage: 100 },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithManyGroups}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const expandButton = screen.getByText('+2 more conditions')
            await userEvent.click(expandButton)

            expect(screen.getByText('25% of all users')).toBeInTheDocument()
            expect(screen.getByText('50% of all users')).toBeInTheDocument()
            expect(screen.getByText('75% of all users')).toBeInTheDocument()
            expect(screen.getByText('100% of all users')).toBeInTheDocument()
            expect(screen.getByText('Show less')).toBeInTheDocument()
        })

        it('collapses back when "Show less" is clicked', async () => {
            const flagWithManyGroups: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        { properties: [], rollout_percentage: 25 },
                        { properties: [], rollout_percentage: 50 },
                        { properties: [], rollout_percentage: 75 },
                        { properties: [], rollout_percentage: 100 },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithManyGroups}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            const expandButton = screen.getByText('+2 more conditions')
            await userEvent.click(expandButton)

            const collapseButton = screen.getByText('Show less')
            await userEvent.click(collapseButton)

            expect(screen.queryByText('75% of all users')).not.toBeInTheDocument()
            expect(screen.queryByText('100% of all users')).not.toBeInTheDocument()
            expect(screen.getByText('+2 more conditions')).toBeInTheDocument()
        })

        it('does not show expand/collapse when there are 2 or fewer conditions', () => {
            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={baseFeatureFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.queryByText(/more condition/)).not.toBeInTheDocument()
            expect(screen.queryByText('Show less')).not.toBeInTheDocument()
        })
    })

    describe('complex targeting scenarios', () => {
        it('shows combined rollout and property conditions', () => {
            const complexFlag: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [
                                { key: 'email', value: 'test@example.com', type: 'person', operator: 'exact' },
                            ] as any,
                            rollout_percentage: 50,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={complexFlag}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('50% of users matching 1 condition')).toBeInTheDocument()
        })

        it('handles null rollout percentage as no rollout', () => {
            const flagWithNullRollout: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: null,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithNullRollout}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('all users')).toBeInTheDocument()
        })

        it('handles undefined rollout percentage as no rollout', () => {
            const flagWithUndefinedRollout: FeatureFlagType = {
                ...baseFeatureFlag,
                filters: {
                    ...baseFeatureFlag.filters,
                    groups: [
                        {
                            properties: [],
                            rollout_percentage: undefined,
                        },
                    ],
                },
            }

            render(
                <VariantsPanelLinkFeatureFlag
                    linkedFeatureFlag={flagWithUndefinedRollout}
                    setShowFeatureFlagSelector={mockSetShowFeatureFlagSelector}
                />
            )

            expect(screen.getByText('all users')).toBeInTheDocument()
        })
    })
})
