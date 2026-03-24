import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { FeatureFlagForm } from './FeatureFlagForm'
import { featureFlagLogic } from './featureFlagLogic'

const MOCK_MULTIVARIATE_FLAG: FeatureFlagType = {
    id: 1,
    name: 'Test Flag',
    key: 'test-flag',
    active: true,
    ensure_experience_continuity: false,
    filters: {
        groups: [],
        multivariate: {
            variants: [
                { key: 'control', name: 'Control', rollout_percentage: 33 },
                { key: 'test-a', name: 'Test A', rollout_percentage: 33 },
                { key: 'test-b', name: 'Test B', rollout_percentage: 34 },
            ],
        },
        payloads: { 0: { option: 'default' }, 1: { option: 'variant-a' }, 2: { option: 'variant-b' } },
    },
    deleted: false,
    created_at: '2023-01-01T00:00:00Z',
    created_by: null,
    is_simple_flag: false,
    rollout_percentage: null,
    can_edit: true,
    tags: [],
}

describe('FeatureFlagForm - Expand/Collapse Buttons', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/1/`]: () => [200, MOCK_MULTIVARIATE_FLAG],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/1/status/`]: () => [
                    200,
                    { status: 'active', reason: 'Feature flag is active' },
                ],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/feature_flags/1/dependent_flags/`]: () => [200, []],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/tags/`]: () => [200, { results: [] }],
                [`/api/projects/${MOCK_DEFAULT_PROJECT.id}/experiments/`]: () => [200, { results: [] }],
            },
        })

        initKeaTests()
        logic = featureFlagLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    const renderComponent = (): any => {
        return render(<FeatureFlagForm id={1} />)
    }

    describe('Expand All Button', () => {
        it('renders expand all button', async () => {
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
            })
        })

        it('has correct icon and tooltip', async () => {
            renderComponent()

            await waitFor(() => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                expect(expandButton).toHaveAttribute('aria-label', 'Expand all variants')
            })
        })

        it('expands all variants when clicked', async () => {
            const user = userEvent.setup()
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
            })

            await expectLogic(logic, () => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                user.click(expandButton)
            }).toDispatchActions(['setOpenVariants'])

            // Verify all variants are in openVariants array
            await waitFor(() => {
                const openVariants = logic.values.openVariants
                expect(openVariants).toHaveLength(3)
                expect(openVariants).toContain('control')
                expect(openVariants).toContain('test-a')
                expect(openVariants).toContain('test-b')
            })
        })

        it('works with variants that have no key (fallback to index)', async () => {
            // Set up variants without keys to test fallback
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'Variant 1', rollout_percentage: 50 },
                            { key: '', name: 'Variant 2', rollout_percentage: 50 },
                        ],
                    },
                },
            })

            const user = userEvent.setup()
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
            })

            await expectLogic(logic, () => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                user.click(expandButton)
            }).toDispatchActions(['setOpenVariants'])

            // Should use fallback keys like variant-0, variant-1
            await waitFor(() => {
                const openVariants = logic.values.openVariants
                expect(openVariants).toContain('variant-0')
                expect(openVariants).toContain('variant-1')
            })
        })
    })

    describe('Collapse All Button', () => {
        it('renders collapse all button', async () => {
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('has correct icon and tooltip', async () => {
            renderComponent()

            await waitFor(() => {
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                expect(collapseButton).toHaveAttribute('aria-label', 'Collapse all variants')
            })
        })

        it('collapses all variants when clicked', async () => {
            const user = userEvent.setup()
            renderComponent()

            // First expand all variants
            logic.actions.setOpenVariants(['control', 'test-a', 'test-b'])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })

            await expectLogic(logic, () => {
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                user.click(collapseButton)
            }).toDispatchActions(['setOpenVariants'])

            // Verify all variants are collapsed (openVariants should be empty)
            await waitFor(() => {
                expect(logic.values.openVariants).toEqual([])
            })
        })

        it('works when no variants are expanded', async () => {
            const user = userEvent.setup()
            renderComponent()

            // Start with no expanded variants
            logic.actions.setOpenVariants([])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })

            await expectLogic(logic, () => {
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                user.click(collapseButton)
            }).toDispatchActions(['setOpenVariants'])

            // Should still be empty array
            await waitFor(() => {
                expect(logic.values.openVariants).toEqual([])
            })
        })
    })

    describe('Button Integration', () => {
        it('both buttons work together correctly', async () => {
            const user = userEvent.setup()
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })

            // Start collapsed
            expect(logic.values.openVariants).toEqual([])

            // Expand all
            await expectLogic(logic, () => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                user.click(expandButton)
            }).toDispatchActions(['setOpenVariants'])

            await waitFor(() => {
                expect(logic.values.openVariants).toHaveLength(3)
            })

            // Collapse all
            await expectLogic(logic, () => {
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                user.click(collapseButton)
            }).toDispatchActions(['setOpenVariants'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual([])
            })
        })

        it('buttons are positioned correctly with distribute equally button', async () => {
            renderComponent()

            await waitFor(() => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                const distributeButton = screen.getByRole('button', { name: /distribute rollout percentages equally/i })

                // All buttons should be present
                expect(expandButton).toBeInTheDocument()
                expect(collapseButton).toBeInTheDocument()
                expect(distributeButton).toBeInTheDocument()

                // They should be in the same container (variants header)
                const buttonsContainer = expandButton.closest('div')
                expect(buttonsContainer).toContainElement(collapseButton)
                expect(buttonsContainer).toContainElement(distributeButton)
            })
        })
    })

    describe('Edge Cases', () => {
        it('handles empty variants array gracefully', async () => {
            // Set up flag with no variants
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    groups: [],
                    multivariate: {
                        variants: [],
                    },
                },
            })

            const user = userEvent.setup()
            renderComponent()

            // Buttons might not be visible if there are no variants, but if they are, they shouldn't crash
            const expandButtons = screen.queryAllByRole('button', { name: /expand all variants/i })
            if (expandButtons.length > 0) {
                expect(() => user.click(expandButtons[0])).not.toThrow()
            }
        })

        it('handles single variant correctly', async () => {
            // Set up flag with single variant
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [{ key: 'single', name: 'Single Variant', rollout_percentage: 100 }],
                    },
                },
            })

            const user = userEvent.setup()
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
            })

            await expectLogic(logic, () => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                user.click(expandButton)
            }).toDispatchActions(['setOpenVariants'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['single'])
            })
        })
    })

    describe('Contextual Visibility', () => {
        it('shows expand all button only when not all variants are expanded', async () => {
            renderComponent()

            // Initially no variants expanded - expand button should be visible
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
                expect(screen.queryByRole('button', { name: /collapse all variants/i })).not.toBeInTheDocument()
            })

            // Expand all variants
            logic.actions.setOpenVariants(['control', 'test-a', 'test-b'])

            await waitFor(() => {
                expect(screen.queryByRole('button', { name: /expand all variants/i })).not.toBeInTheDocument()
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('shows collapse all button only when at least one variant is expanded', async () => {
            renderComponent()

            // Start with no expanded variants
            logic.actions.setOpenVariants([])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
                expect(screen.queryByRole('button', { name: /collapse all variants/i })).not.toBeInTheDocument()
            })

            // Expand one variant
            logic.actions.setOpenVariants(['control'])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })

            // Expand all variants
            logic.actions.setOpenVariants(['control', 'test-a', 'test-b'])

            await waitFor(() => {
                expect(screen.queryByRole('button', { name: /expand all variants/i })).not.toBeInTheDocument()
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('shows both buttons in partially expanded state', async () => {
            renderComponent()

            // Set partial expansion (only 2 of 3 variants expanded)
            logic.actions.setOpenVariants(['control', 'test-a'])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('does not show expand all button when there is only one variant', async () => {
            // Set up flag with single variant
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [{ key: 'single', name: 'Single Variant', rollout_percentage: 100 }],
                    },
                },
            })

            renderComponent()

            await waitFor(() => {
                // With only one variant, expand all doesn't make sense
                expect(screen.queryByRole('button', { name: /expand all variants/i })).not.toBeInTheDocument()
                // Collapse all should not be visible since nothing is expanded initially
                expect(screen.queryByRole('button', { name: /collapse all variants/i })).not.toBeInTheDocument()
            })

            // Expand the single variant
            logic.actions.setOpenVariants(['single'])

            await waitFor(() => {
                // Still no expand all button with single variant
                expect(screen.queryByRole('button', { name: /expand all variants/i })).not.toBeInTheDocument()
                // Collapse all should be visible now
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('handles empty variants array gracefully', async () => {
            // Set up flag with no variants
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    groups: [],
                    multivariate: {
                        variants: [],
                    },
                },
            })

            renderComponent()

            // With no variants, no buttons should be visible
            await waitFor(() => {
                expect(screen.queryByRole('button', { name: /expand all variants/i })).not.toBeInTheDocument()
                expect(screen.queryByRole('button', { name: /collapse all variants/i })).not.toBeInTheDocument()
            })
        })
    })

    describe('Accessibility', () => {
        it('buttons have proper ARIA labels when visible', async () => {
            renderComponent()

            await waitFor(() => {
                const expandButton = screen.getByRole('button', { name: /expand all variants/i })
                expect(expandButton).toHaveAttribute('aria-label', 'Expand all variants')
            })

            // Expand all, then check collapse button
            logic.actions.setOpenVariants(['control', 'test-a', 'test-b'])

            await waitFor(() => {
                const collapseButton = screen.getByRole('button', { name: /collapse all variants/i })
                expect(collapseButton).toHaveAttribute('aria-label', 'Collapse all variants')
            })
        })

        it('buttons are keyboard accessible when present', async () => {
            const user = userEvent.setup()
            renderComponent()

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /expand all variants/i })).toBeInTheDocument()
            })

            // Focus on expand button using tab
            await user.tab()
            // Find and focus the expand button (may need multiple tabs depending on DOM structure)
            const expandButton = screen.getByRole('button', { name: /expand all variants/i })
            expandButton.focus()

            // Press Enter to activate
            await expectLogic(logic, () => {
                user.keyboard('{Enter}')
            }).toDispatchActions(['setOpenVariants'])

            await waitFor(() => {
                expect(logic.values.openVariants).toHaveLength(3)
            })
        })
    })
})
