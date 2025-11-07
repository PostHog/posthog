import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { VariantsPanel } from './VariantsPanel'

// Mock JSONEditorInput since it uses Monaco editor which doesn't work in Jest
jest.mock('scenes/feature-flags/JSONEditorInput', () => ({
    JSONEditorInput: ({ onChange, value, placeholder, readOnly }: any) => (
        <input
            data-testid="json-editor-mock"
            value={value || ''}
            onChange={(e) => onChange?.(e.target.value)}
            placeholder={placeholder}
            readOnly={readOnly}
        />
    ),
}))

// Suppress react-modal warnings in tests
beforeAll(() => {
    const modalRoot = document.createElement('div')
    modalRoot.setAttribute('id', 'root')
    document.body.appendChild(modalRoot)
})

describe('VariantsPanel', () => {
    const mockUpdateFeatureFlag = jest.fn()

    const defaultExperiment: Experiment = {
        ...NEW_EXPERIMENT,
        name: 'Test Experiment',
        feature_flag_key: 'test-experiment',
        parameters: {
            feature_flag_variants: [
                { key: 'control', rollout_percentage: 50 },
                { key: 'test', rollout_percentage: 50 },
            ],
        },
    }

    const mockEligibleFlags = [
        {
            id: 1,
            key: 'eligible-flag-1',
            name: 'Eligible Flag 1',
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'variant-a', rollout_percentage: 50 },
                    ],
                },
            },
        },
        {
            id: 2,
            key: 'eligible-flag-2',
            name: 'Eligible Flag 2',
            filters: {
                groups: [],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'variant-a', rollout_percentage: 33 },
                        { key: 'variant-b', rollout_percentage: 34 },
                    ],
                },
            },
        },
    ]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/experiments/eligible_feature_flags/': (req) => {
                    const url = new URL(req.url)
                    const search = url.searchParams.get('search')

                    if (search) {
                        const filtered = mockEligibleFlags.filter((flag) =>
                            flag.key.toLowerCase().includes(search.toLowerCase())
                        )
                        return [200, { results: filtered, count: filtered.length }]
                    }

                    return [200, { results: mockEligibleFlags, count: mockEligibleFlags.length }]
                },
                '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    describe('rendering', () => {
        it('renders mode selection cards', () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            expect(screen.getByText('Create new feature flag')).toBeInTheDocument()
            expect(screen.getByText('Link existing feature flag')).toBeInTheDocument()
        })

        it('defaults to create mode', () => {
            const { container } = render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const createCard = cards[0]
            const linkCard = cards[1]

            expect(createCard).toHaveClass('border-accent')
            expect(linkCard).not.toHaveClass('border-accent')
        })

        it('renders create feature flag panel in create mode', () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
            expect(screen.getByText('Variant keys')).toBeInTheDocument()
        })
    })

    describe('mode switching', () => {
        it('switches to link mode when clicking link card', async () => {
            const { container } = render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const linkCard = cards[1]

            await userEvent.click(linkCard)

            // Should show link mode UI
            expect(screen.getByText('Selected Feature Flag')).toBeInTheDocument()
            expect(screen.getByText('No feature flag selected')).toBeInTheDocument()
        })

        it('switches back to create mode when clicking create card', async () => {
            const { container } = render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const linkCard = cards[1]
            const createCard = cards[0]

            // Switch to link mode
            await userEvent.click(linkCard)
            expect(screen.getByText('No feature flag selected')).toBeInTheDocument()

            // Switch back to create mode
            await userEvent.click(createCard)
            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
            expect(screen.getByText('Variant keys')).toBeInTheDocument()
        })

        it('highlights selected mode card', async () => {
            const { container } = render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const createCard = cards[0]
            const linkCard = cards[1]

            // Initially create mode is selected
            expect(createCard).toHaveClass('border-accent')
            expect(linkCard).not.toHaveClass('border-accent')

            // Click link mode
            await userEvent.click(linkCard)

            // Link mode should be selected
            const updatedCards = container.querySelectorAll('[role="button"]')
            expect(updatedCards[1]).toHaveClass('border-accent')
            expect(updatedCards[0]).not.toHaveClass('border-accent')
        })
    })

    describe('link existing feature flag', () => {
        it('shows select button in empty state', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            expect(selectButton).toBeInTheDocument()
        })

        it('opens modal when clicking select button', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            // Click select button
            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Modal should open
            expect(screen.getByText('Choose an existing feature flag')).toBeInTheDocument()
        })

        it('displays available feature flags in modal', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for feature flags to load
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
                expect(screen.getByText('eligible-flag-2')).toBeInTheDocument()
            })
        })

        it('filters feature flags by search', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for flags to load, then search
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const searchInput = screen.getByPlaceholderText(/search for feature flags/i)
            await userEvent.type(searchInput, 'flag-1')

            // Should only show matching flag
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
                expect(screen.queryByText('eligible-flag-2')).not.toBeInTheDocument()
            })
        })

        it('selects feature flag and closes modal', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Wait for modal to close and flag to be displayed
            await waitFor(() => {
                expect(screen.queryByText('Choose an existing feature flag')).not.toBeInTheDocument()
            })
            expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
        })

        it('displays selected flag with variants', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Should display variants
            await waitFor(() => {
                const variantsSection = screen.getAllByText(/variants/i).find((el) => {
                    return el.className.includes('uppercase') && el.textContent === 'Variants'
                })
                expect(variantsSection).toBeInTheDocument()
            })
            expect(screen.getByText('control')).toBeInTheDocument()
            expect(screen.getByText('variant-a')).toBeInTheDocument()
        })

        it('shows change button for selected flag', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Should show change button
            expect(screen.getByRole('button', { name: /change/i })).toBeInTheDocument()
        })

        it('reopens modal when clicking change button', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode, open modal, select flag
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Click change button
            const changeButton = screen.getByRole('button', { name: /change/i })
            await userEvent.click(changeButton)

            // Modal should reopen
            expect(screen.getByText('Choose an existing feature flag')).toBeInTheDocument()
        })
    })

    describe('edge cases', () => {
        it('handles empty feature flags list', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/experiments/eligible_feature_flags/': () => [
                        200,
                        { results: [], count: 0 },
                    ],
                    '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
                },
            })

            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and open modal
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            // Wait for empty state to show
            await waitFor(() => {
                expect(screen.getByText(/no feature flags match/i)).toBeInTheDocument()
            })
        })

        it('handles experiment without feature flag key', () => {
            const experimentWithoutKey = {
                ...NEW_EXPERIMENT,
                name: 'Test',
            }

            render(
                <VariantsPanel
                    experiment={experimentWithoutKey}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Should still render without errors
            expect(screen.getByText('Create new feature flag')).toBeInTheDocument()
        })
    })

    describe('variant validation', () => {
        it('shows error when variant key is empty', async () => {
            const experimentWithEmptyKey: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test Experiment',
                feature_flag_key: 'test-experiment',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '', rollout_percentage: 50 },
                    ],
                },
            }

            render(
                <VariantsPanel
                    experiment={experimentWithEmptyKey}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Should show error message
            expect(screen.getByText('All variants must have a key.')).toBeInTheDocument()
        })

        it('shows error when variant keys are duplicated', async () => {
            const experimentWithDuplicateKeys: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test Experiment',
                feature_flag_key: 'test-experiment',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'control', rollout_percentage: 50 },
                    ],
                },
            }

            render(
                <VariantsPanel
                    experiment={experimentWithDuplicateKeys}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Should show error message
            expect(screen.getByText('Variant keys must be unique.')).toBeInTheDocument()
        })

        it.skip('shows error when variant has zero rollout and sum is not 100', async () => {
            const experimentWithZeroRollout: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test Experiment',
                feature_flag_key: 'test-experiment',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 0 },
                    ],
                },
            }

            render(
                <VariantsPanel
                    experiment={experimentWithZeroRollout}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Should show error message
            expect(screen.getByText('All variants must have a rollout percentage greater than 0.')).toBeInTheDocument()
        })

        it('does not show zero rollout error when sum is 100', async () => {
            const experimentWithValidZeroRollout: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test Experiment',
                feature_flag_key: 'test-experiment',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 100 },
                        { key: 'test', rollout_percentage: 0 },
                    ],
                },
            }

            render(
                <VariantsPanel
                    experiment={experimentWithValidZeroRollout}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Should not show zero rollout error
            expect(
                screen.queryByText('All variants must have a rollout percentage greater than 0.')
            ).not.toBeInTheDocument()
        })

        it('highlights variant with error', async () => {
            const experimentWithEmptyKey: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test Experiment',
                feature_flag_key: 'test-experiment',
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '', rollout_percentage: 50 },
                    ],
                },
            }

            const { container } = render(
                <VariantsPanel
                    experiment={experimentWithEmptyKey}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Find variant rows
            const variantRows = container.querySelectorAll('.grid.grid-cols-24')

            // First variant (control) should not have error highlighting
            expect(variantRows[1]).not.toHaveClass('bg-danger-highlight')

            // Second variant (empty key) should have error highlighting
            expect(variantRows[2]).toHaveClass('bg-danger-highlight')
            expect(variantRows[2]).toHaveClass('border-danger')
        })
    })

    describe('callback payloads', () => {
        it('calls updateFeatureFlag with correct structure when selecting linked flag', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            // Switch to link mode and select a flag
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Verify callback was called with correct structure
            await waitFor(() => {
                expect(mockUpdateFeatureFlag).toHaveBeenCalledWith({
                    feature_flag_key: 'eligible-flag-1',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'variant-a', rollout_percentage: 50 },
                        ],
                    },
                })
            })
        })
    })

    describe('state restoration', () => {
        it('persists linked flag selection when switching link→create→link', async () => {
            render(
                <VariantsPanel
                    experiment={defaultExperiment}
                    updateFeatureFlag={mockUpdateFeatureFlag}
                    onPrevious={() => {}}
                    onNext={() => {}}
                />
            )

            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))!
            const createCard = cards.find((card) => card.textContent?.includes('Create new'))!

            // Step 1: Switch to link mode and select a flag
            await userEvent.click(linkCard)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            await userEvent.click(selectButton)

            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            const flagRows = screen.getAllByRole('row')
            const firstFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-1'))
            const selectFlagButton = within(firstFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Verify flag is selected and displayed
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
                expect(screen.getByText('control')).toBeInTheDocument()
                expect(screen.getByText('variant-a')).toBeInTheDocument()
            })

            // Step 2: Switch to create mode
            await userEvent.click(createCard)

            // Should show create mode UI
            expect(screen.getByText('Feature flag key')).toBeInTheDocument()

            // Step 3: Switch back to link mode
            await userEvent.click(linkCard)

            // Should still show the previously selected flag
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
                expect(screen.getByText('control')).toBeInTheDocument()
                expect(screen.getByText('variant-a')).toBeInTheDocument()
            })

            // Verify the flag is still displayed with its variants (not showing empty state)
            expect(screen.queryByText('No feature flag selected')).not.toBeInTheDocument()
        })
    })
})
