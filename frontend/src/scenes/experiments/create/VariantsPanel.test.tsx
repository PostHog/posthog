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
                '/api/projects/@current/feature_flags/': (req) => {
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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            expect(screen.getByText('Create new feature flag')).toBeInTheDocument()
            expect(screen.getByText('Link existing feature flag')).toBeInTheDocument()
        })

        it('defaults to create mode', () => {
            const { container } = render(
                <VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const createCard = cards[0]
            const linkCard = cards[1]

            expect(createCard).toHaveClass('border-accent')
            expect(linkCard).not.toHaveClass('border-accent')
        })

        it('renders create feature flag panel in create mode', () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
            expect(screen.getByText('Variant keys')).toBeInTheDocument()
        })
    })

    describe('mode switching', () => {
        it('switches to link mode when clicking link card', async () => {
            const { container } = render(
                <VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />
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
                <VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />
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
                <VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />
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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // Switch to link mode
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            const selectButton = screen.getByRole('button', { name: /select feature flag/i })
            expect(selectButton).toBeInTheDocument()
        })

        it('opens modal when clicking select button', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            expect(screen.getByText('VARIANTS:')).toBeInTheDocument()
            expect(screen.getByText('control')).toBeInTheDocument()
            expect(screen.getByText('variant-a')).toBeInTheDocument()
        })

        it('shows change button for selected flag', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // Switch to link mode, open modal, select flag
            const cards = screen.getAllByRole('button')
            const linkCard = cards.find((card) => card.textContent?.includes('Link existing'))
            await userEvent.click(linkCard!)

            let selectButton = screen.getByRole('button', { name: /select feature flag/i })
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
                    '/api/projects/@current/feature_flags/': () => [200, { results: [], count: 0 }],
                    '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
                },
            })

            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

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

            render(<VariantsPanel experiment={experimentWithoutKey} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // Should still render without errors
            expect(screen.getByText('Create new feature flag')).toBeInTheDocument()
        })
    })
})
