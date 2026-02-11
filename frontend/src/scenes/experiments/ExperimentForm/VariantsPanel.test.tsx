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

    const getFeatureFlagInput = (): HTMLElement => {
        const field = screen.getByText('Feature flag key').closest('.Field')
        if (!field) {
            throw new Error('Feature flag key field not found')
        }
        return within(field as HTMLElement).getByRole('textbox')
    }

    const openFeatureFlagAutocomplete = async (searchText = 'eligible'): Promise<void> => {
        const input = getFeatureFlagInput()
        await userEvent.clear(input)
        await userEvent.type(input, searchText)
    }

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
        it('renders feature flag key input', () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
        })

        it('shows variant keys section when feature flag key is set', () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            expect(screen.getByText('Variant key')).toBeInTheDocument()
        })
    })

    describe('create new feature flag', () => {
        it('replaces spaces with dashes in feature flag key', async () => {
            const experimentWithoutKey: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test',
                feature_flag_key: '',
            }

            render(<VariantsPanel experiment={experimentWithoutKey} updateFeatureFlag={mockUpdateFeatureFlag} />)

            const input = getFeatureFlagInput()
            await userEvent.type(input, 'my flag key')

            // The input transform converts spaces to dashes as shown in the dropdown
            // Now select the custom value from the dropdown to trigger handleFeatureFlagSelection
            await waitFor(() => {
                expect(screen.getByText('my-flag-key')).toBeInTheDocument()
            })

            // Click the transformed option in the dropdown
            await userEvent.click(screen.getByText('my-flag-key'))

            // Verify the callback was called with the transformed key
            await waitFor(() => {
                expect(mockUpdateFeatureFlag).toHaveBeenCalledWith(
                    expect.objectContaining({
                        feature_flag_key: 'my-flag-key',
                    })
                )
            })
        })

        it('shows linked feature flag box when typing matches existing eligible flag', async () => {
            const existingFlag = {
                id: 3,
                key: 'existing-key',
                name: 'Existing Flag',
                filters: {
                    groups: [],
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                },
            }

            useMocks({
                get: {
                    '/api/projects/@current/experiments/eligible_feature_flags/': (req) => {
                        const url = new URL(req.url)
                        const search = url.searchParams.get('search')
                        if (search) {
                            const allFlags = [...mockEligibleFlags, existingFlag]
                            const filtered = allFlags.filter((flag) =>
                                flag.key.toLowerCase().includes(search.toLowerCase())
                            )
                            return [200, { results: filtered, count: filtered.length }]
                        }
                        return [
                            200,
                            { results: [...mockEligibleFlags, existingFlag], count: mockEligibleFlags.length + 1 },
                        ]
                    },
                    '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
                },
            })

            const experimentWithoutKey: Experiment = {
                ...NEW_EXPERIMENT,
                name: 'Test',
                feature_flag_key: '',
            }

            render(<VariantsPanel experiment={experimentWithoutKey} updateFeatureFlag={mockUpdateFeatureFlag} />)

            const input = getFeatureFlagInput()
            // Type partial key so we can distinguish between create option ("existing") and existing flag ("existing-key")
            await userEvent.type(input, 'existing')

            // Wait for the matching existing flag to appear in dropdown
            await waitFor(() => {
                expect(screen.getByText('existing-key')).toBeInTheDocument()
            })

            // Click on the existing flag option (create option would show "existing", not "existing-key")
            await userEvent.click(screen.getByText('existing-key'))

            // Should show linked feature flag box instead of validation error
            await waitFor(() => {
                expect(screen.getByText('Linked feature flag')).toBeInTheDocument()
            })

            // Verify the callback was called with the linked flag data
            await waitFor(() => {
                expect(mockUpdateFeatureFlag).toHaveBeenCalledWith({
                    feature_flag_key: 'existing-key',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                })
            })
        })

        it('clears selection and hides variant panel when input is cleared', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // First select an existing flag
            await openFeatureFlagAutocomplete()

            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Verify linked flag is shown
            await waitFor(() => {
                expect(screen.getByText('Linked feature flag')).toBeInTheDocument()
            })

            // Now clear the input by clicking the clear button (x)
            const clearButton = screen.getByRole('button', { name: /clear/i })
            await userEvent.click(clearButton)

            // Should call updateFeatureFlag to clear the key
            await waitFor(() => {
                expect(mockUpdateFeatureFlag).toHaveBeenCalledWith({
                    feature_flag_key: undefined,
                    parameters: {
                        feature_flag_variants: undefined,
                    },
                })
            })

            // Variant panel should be hidden (no "Linked feature flag" or "Variant keys")
            await waitFor(() => {
                expect(screen.queryByText('Linked feature flag')).not.toBeInTheDocument()
            })
        })
    })

    describe('link existing feature flag', () => {
        it('displays available feature flags in dropdown', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for feature flags to load
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
                expect(screen.getByText('eligible-flag-2')).toBeInTheDocument()
            })
        })

        it('selects feature flag from dropdown', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

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

        it('displays selected flag with variants after selection', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Should display linked flag section with variants
            await waitFor(() => {
                expect(screen.getByText('Linked feature flag')).toBeInTheDocument()
                // Verify the variants from the linked flag are displayed
                expect(screen.getByText('control')).toBeInTheDocument()
                expect(screen.getByText('variant-a')).toBeInTheDocument()
            })
        })

        it('shows change button for selected flag', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Should show change button
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /change/i })).toBeInTheDocument()
            })
        })

        it('opens modal when clicking change button', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Click change button
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /change/i })).toBeInTheDocument()
            })
            const changeButton = screen.getByRole('button', { name: /change/i })
            await userEvent.click(changeButton)

            // Modal should open
            expect(screen.getByText('Choose an existing feature flag')).toBeInTheDocument()
        })

        it('filters feature flags by search in modal', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Click change button to open modal
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /change/i })).toBeInTheDocument()
            })
            const changeButton = screen.getByRole('button', { name: /change/i })
            await userEvent.click(changeButton)

            // Search in modal
            const searchInput = screen.getByPlaceholderText(/search for feature flags/i)
            await userEvent.type(searchInput, 'flag-1')

            // Should only show matching flag
            await waitFor(() => {
                expect(screen.getAllByText('eligible-flag-1').length).toBeGreaterThan(0)
                expect(screen.queryByText('eligible-flag-2')).not.toBeInTheDocument()
            })
        })

        it('selects feature flag from modal and closes it', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            // Wait for flags to load, then select first flag
            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

            // Click change button to open modal
            await waitFor(() => {
                expect(screen.getByRole('button', { name: /change/i })).toBeInTheDocument()
            })
            const changeButton = screen.getByRole('button', { name: /change/i })
            await userEvent.click(changeButton)

            // Wait for modal to show flags
            await waitFor(() => {
                expect(screen.getByText('Choose an existing feature flag')).toBeInTheDocument()
            })

            // Select second flag from modal
            const flagRows = screen.getAllByRole('row')
            const secondFlagRow = flagRows.find((row) => row.textContent?.includes('eligible-flag-2'))
            const selectFlagButton = within(secondFlagRow!).getByRole('button', { name: /select/i })
            await userEvent.click(selectFlagButton)

            // Modal should close
            await waitFor(() => {
                expect(screen.queryByText('Choose an existing feature flag')).not.toBeInTheDocument()
            })
        })
    })

    describe('edge cases', () => {
        it('handles empty feature flags list in modal', async () => {
            useMocks({
                get: {
                    '/api/projects/@current/experiments/eligible_feature_flags/': () => [
                        200,
                        { results: [], count: 0 },
                    ],
                    '/api/projects/@current/experiments': () => [200, { results: [], count: 0 }],
                },
            })

            // Create experiment with linked flag to show the change button
            const experimentWithLinkedFlag: Experiment = {
                ...defaultExperiment,
                feature_flag_key: 'linked-flag',
            }

            render(<VariantsPanel experiment={experimentWithLinkedFlag} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // The component should render without errors
            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
        })

        it('handles experiment without feature flag key', () => {
            const experimentWithoutKey = {
                ...NEW_EXPERIMENT,
                name: 'Test',
            }

            render(<VariantsPanel experiment={experimentWithoutKey} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // Should still render without errors
            expect(screen.getByText('Feature flag key')).toBeInTheDocument()
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

            render(<VariantsPanel experiment={experimentWithEmptyKey} updateFeatureFlag={mockUpdateFeatureFlag} />)

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

            render(<VariantsPanel experiment={experimentWithDuplicateKeys} updateFeatureFlag={mockUpdateFeatureFlag} />)

            // Should show error message
            expect(screen.getByText('Variant keys must be unique.')).toBeInTheDocument()
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
                <VariantsPanel experiment={experimentWithEmptyKey} updateFeatureFlag={mockUpdateFeatureFlag} />
            )

            // Find variant rows in the table
            const variantRows = container.querySelectorAll('tbody tr')

            // First variant (control) should not have error highlighting
            expect(variantRows[0]).not.toHaveClass('bg-danger-highlight')

            // Second variant (empty key) should have error highlighting
            expect(variantRows[1]).toHaveClass('bg-danger-highlight')
            expect(variantRows[1]).toHaveClass('border-danger')
        })
    })

    describe('callback payloads', () => {
        it('calls updateFeatureFlag with correct structure when selecting linked flag', async () => {
            render(<VariantsPanel experiment={defaultExperiment} updateFeatureFlag={mockUpdateFeatureFlag} />)

            await openFeatureFlagAutocomplete()

            await waitFor(() => {
                expect(screen.getByText('eligible-flag-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByText('eligible-flag-1'))

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
})
