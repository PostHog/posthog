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
        it('renders collapse all button when variants are expanded', async () => {
            renderComponent()

            // First expand some variants
            logic.actions.setOpenVariants(['control', 'test-a'])

            await waitFor(() => {
                expect(screen.getByRole('button', { name: /collapse all variants/i })).toBeInTheDocument()
            })
        })

        it('has correct icon and tooltip', async () => {
            renderComponent()

            // First expand some variants so collapse button is visible
            logic.actions.setOpenVariants(['control', 'test-a'])

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
            renderComponent()

            // Start with no expanded variants
            logic.actions.setOpenVariants([])

            await waitFor(() => {
                // Collapse all button should NOT be visible when no variants are expanded
                expect(screen.queryByRole('button', { name: /collapse all variants/i })).not.toBeInTheDocument()
            })

            // Since no collapse button is visible, we can't test clicking it
            // This test just verifies the correct visibility behavior
            expect(logic.values.openVariants).toEqual([])
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

    describe('Drag and Drop Integration', () => {
        it('preserves expanded state when dragging variants with keys', async () => {
            renderComponent()

            // Expand the first two variants
            logic.actions.setOpenVariants(['control', 'test-a'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['control', 'test-a'])
            })

            // Simulate reordering variants (control moves from index 0 to index 2)
            logic.actions.reorderVariants(0, 2)

            await waitFor(() => {
                // openVariants should still contain the same keys since they have proper keys
                expect(logic.values.openVariants).toEqual(['control', 'test-a'])
            })
        })

        it('properly remaps openVariants when dragging keyless variants', async () => {
            // Set up variants without keys
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'Variant A', rollout_percentage: 33 },
                            { key: '', name: 'Variant B', rollout_percentage: 33 },
                            { key: '', name: 'Variant C', rollout_percentage: 34 },
                        ],
                    },
                },
            })

            renderComponent()

            // Expand first and third variants (variant-0 and variant-2)
            logic.actions.setOpenVariants(['variant-0', 'variant-2'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['variant-0', 'variant-2'])
            })

            // Move first variant (index 0) to last position (index 2)
            logic.actions.reorderVariants(0, 2)

            await waitFor(() => {
                // variant-0 becomes variant-2, variant-2 becomes variant-1
                expect(logic.values.openVariants).toEqual(['variant-2', 'variant-1'])
            })
        })

        it('handles complex reordering scenarios with mixed key types', async () => {
            // Set up mixed variants - some with keys, some without
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: 'control', name: 'Control', rollout_percentage: 25 },
                            { key: '', name: 'Keyless 1', rollout_percentage: 25 },
                            { key: '', name: 'Keyless 2', rollout_percentage: 25 },
                            { key: 'test-variant', name: 'Test', rollout_percentage: 25 },
                        ],
                    },
                },
            })

            renderComponent()

            // Expand control (has key) and second keyless variant (variant-1)
            logic.actions.setOpenVariants(['control', 'variant-1'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['control', 'variant-1'])
            })

            // Move keyless variant from index 1 to index 3
            logic.actions.reorderVariants(1, 3)

            await waitFor(() => {
                // 'control' stays the same (has key), 'variant-1' becomes 'variant-2'
                expect(logic.values.openVariants).toEqual(['control', 'variant-2'])
            })
        })

        it('handles edge cases with single variant', async () => {
            // Set up single keyless variant
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [{ key: '', name: 'Single Variant', rollout_percentage: 100 }],
                    },
                },
            })

            renderComponent()

            // Expand the single variant
            logic.actions.setOpenVariants(['variant-0'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['variant-0'])
            })

            // Try to reorder (should be a no-op with single variant)
            logic.actions.reorderVariants(0, 0)

            await waitFor(() => {
                // Should remain the same
                expect(logic.values.openVariants).toEqual(['variant-0'])
            })
        })

        it('handles empty openVariants gracefully during reordering', async () => {
            renderComponent()

            // Start with no expanded variants
            logic.actions.setOpenVariants([])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual([])
            })

            // Reorder variants
            logic.actions.reorderVariants(0, 2)

            await waitFor(() => {
                // Should remain empty
                expect(logic.values.openVariants).toEqual([])
            })
        })

        it('synchronizes openVariants with moveVariantUp action', async () => {
            // Set up keyless variants
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'First', rollout_percentage: 50 },
                            { key: '', name: 'Second', rollout_percentage: 50 },
                        ],
                    },
                },
            })

            renderComponent()

            // Expand second variant (variant-1)
            logic.actions.setOpenVariants(['variant-1'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['variant-1'])
            })

            // Move second variant up (index 1 to index 0)
            logic.actions.moveVariantUp(1)

            await waitFor(() => {
                // variant-1 becomes variant-0
                expect(logic.values.openVariants).toEqual(['variant-0'])
            })
        })

        it('synchronizes openVariants with moveVariantDown action', async () => {
            // Set up keyless variants
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'First', rollout_percentage: 50 },
                            { key: '', name: 'Second', rollout_percentage: 50 },
                        ],
                    },
                },
            })

            renderComponent()

            // Expand first variant (variant-0)
            logic.actions.setOpenVariants(['variant-0'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['variant-0'])
            })

            // Move first variant down (index 0 to index 1)
            logic.actions.moveVariantDown(0)

            await waitFor(() => {
                // variant-0 becomes variant-1
                expect(logic.values.openVariants).toEqual(['variant-1'])
            })
        })
    })

    describe('Keyless Variant ID Remapping Logic', () => {
        it('demonstrates why remapping is necessary for keyless variants', async () => {
            // Set up 3 keyless variants
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'Original First', rollout_percentage: 33 },
                            { key: '', name: 'Original Second', rollout_percentage: 33 },
                            { key: '', name: 'Original Third', rollout_percentage: 34 },
                        ],
                    },
                },
            })

            renderComponent()

            // Initially: variant-0, variant-1, variant-2 map to indices 0, 1, 2
            // Expand first and third variants (variant-0 and variant-2)
            logic.actions.setOpenVariants(['variant-0', 'variant-2'])

            await waitFor(() => {
                expect(logic.values.openVariants).toEqual(['variant-0', 'variant-2'])
            })

            // MOVE: First variant (index 0) to last position (index 2)
            // This reorders the array: [second, third, first]
            // So now:
            // - Index 0 has "Original Second" (gets ID variant-0)
            // - Index 1 has "Original Third" (gets ID variant-1)
            // - Index 2 has "Original First" (gets ID variant-2)
            logic.actions.reorderVariants(0, 2)

            await waitFor(() => {
                // Without remapping, openVariants would still be ['variant-0', 'variant-2']
                // This would mean:
                // - "Original Second" (now at index 0) would appear expanded ❌
                // - "Original Third" (now at index 1) would appear collapsed ❌
                // - "Original First" (now at index 2) would appear expanded ✅

                // With remapping:
                // - variant-0 (Original First) moved to index 2 → becomes variant-2
                // - variant-2 (Original Third) moved to index 1 → becomes variant-1
                expect(logic.values.openVariants).toEqual(['variant-2', 'variant-1'])

                // This means:
                // - "Original Second" (index 0, variant-0) appears collapsed ✅
                // - "Original Third" (index 1, variant-1) appears expanded ✅
                // - "Original First" (index 2, variant-2) appears expanded ✅
            })
        })

        it('verifies the remapping algorithm handles complex multi-step reordering', async () => {
            // Set up 4 keyless variants for more complex reordering
            logic.actions.setFeatureFlag({
                ...MOCK_MULTIVARIATE_FLAG,
                filters: {
                    ...MOCK_MULTIVARIATE_FLAG.filters,
                    multivariate: {
                        variants: [
                            { key: '', name: 'A', rollout_percentage: 25 },
                            { key: '', name: 'B', rollout_percentage: 25 },
                            { key: '', name: 'C', rollout_percentage: 25 },
                            { key: '', name: 'D', rollout_percentage: 25 },
                        ],
                    },
                },
            })

            renderComponent()

            // Expand variants A (variant-0) and C (variant-2)
            logic.actions.setOpenVariants(['variant-0', 'variant-2'])

            // Move B (index 1) to the end (index 3): [A, C, D, B]
            logic.actions.reorderVariants(1, 3)

            await waitFor(() => {
                // A stays at index 0 → variant-0 unchanged
                // C moves from index 2 to index 1 → variant-2 becomes variant-1
                expect(logic.values.openVariants).toEqual(['variant-0', 'variant-1'])
            })

            // Now move A (index 0) to index 2: [C, D, A, B]
            logic.actions.reorderVariants(0, 2)

            await waitFor(() => {
                // A moves from index 0 to index 2 → variant-0 becomes variant-2
                // C stays at index 0 → variant-1 becomes variant-0
                expect(logic.values.openVariants).toEqual(['variant-2', 'variant-0'])
            })
        })
    })
})
