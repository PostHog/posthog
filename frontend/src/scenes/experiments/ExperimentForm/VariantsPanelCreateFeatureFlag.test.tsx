import '@testing-library/jest-dom'
import { type RenderResult, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { Experiment } from '~/types'

import { NEW_EXPERIMENT } from '../constants'
import { VariantsPanelCreateFeatureFlag } from './VariantsPanelCreateFeatureFlag'

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

describe('VariantsPanelCreateFeatureFlag', () => {
    const mockOnChange = jest.fn()

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

    const renderComponent = (experiment: Experiment): RenderResult => {
        return render(<VariantsPanelCreateFeatureFlag experiment={experiment} onChange={mockOnChange} />)
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/feature_flags/': (req) => {
                    const url = new URL(req.url)
                    const search = url.searchParams.get('search')

                    // Return existing key if searching for it
                    if (search === 'existing-key') {
                        return [
                            200,
                            {
                                results: [{ id: 1, key: 'existing-key', name: 'Existing' }],
                                count: 1,
                            },
                        ]
                    }

                    return [200, { results: [], count: 0 }]
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
        it('renders variant keys section', () => {
            renderComponent(defaultExperiment)

            expect(screen.getByText('Variant key')).toBeInTheDocument()
        })

        it('renders default variants (control and test)', () => {
            renderComponent(defaultExperiment)

            const controlInput = screen.getByDisplayValue('control')
            const testInput = screen.getByDisplayValue('test')

            expect(controlInput).toBeInTheDocument()
            expect(testInput).toBeInTheDocument()
        })

        it('renders variant split labels by default', () => {
            renderComponent(defaultExperiment)

            const splitLabels = screen.getAllByText('50%')
            expect(splitLabels).toHaveLength(2)
        })

        it('renders add variant button', () => {
            renderComponent(defaultExperiment)

            expect(screen.getByRole('button', { name: /add variant/i })).toBeInTheDocument()
        })

        it('renders experience continuity checkbox', () => {
            renderComponent(defaultExperiment)

            expect(screen.getByText(/persist flag across authentication steps/i)).toBeInTheDocument()
            expect(screen.getByRole('checkbox')).toBeInTheDocument()
        })
    })

    describe('variant management', () => {
        it('adds a new variant when clicking add button', async () => {
            renderComponent(defaultExperiment)

            const addButton = screen.getByRole('button', { name: /add variant/i })
            await userEvent.click(addButton)

            expect(mockOnChange).toHaveBeenCalledWith({
                parameters: expect.objectContaining({
                    feature_flag_variants: expect.arrayContaining([
                        expect.objectContaining({ key: 'control' }),
                        expect.objectContaining({ key: 'test' }),
                        expect.objectContaining({ key: 'test-2' }),
                    ]),
                }),
            })
        })

        it('redistributes percentages equally when adding variant', async () => {
            renderComponent(defaultExperiment)

            const addButton = screen.getByRole('button', { name: /add variant/i })
            await userEvent.click(addButton)

            expect(mockOnChange).toHaveBeenCalledWith({
                parameters: expect.objectContaining({
                    feature_flag_variants: expect.arrayContaining([
                        expect.objectContaining({ rollout_percentage: expect.any(Number) }),
                    ]),
                }),
            })

            // Check that percentages sum to 100
            const call = mockOnChange.mock.calls[mockOnChange.mock.calls.length - 1][0]
            const sum = call.parameters.feature_flag_variants.reduce(
                (acc: number, v: any) => acc + v.rollout_percentage,
                0
            )
            expect(sum).toBe(100)
        })

        it('updates variant key when typing', async () => {
            const experimentWithEmptyVariantKey = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '', rollout_percentage: 50 },
                    ],
                },
            }

            renderComponent(experimentWithEmptyVariantKey)

            const variantInputs = screen.getAllByPlaceholderText(/example-variant/)
            await userEvent.type(variantInputs[1], 'treatment')

            // Verify onChange was called with variant updates
            expect(mockOnChange).toHaveBeenCalled()
            const hasVariantUpdate = mockOnChange.mock.calls.some((call) => call[0].parameters?.feature_flag_variants)
            expect(hasVariantUpdate).toBe(true)
        })

        it('updates rollout percentage after enabling custom split', async () => {
            const { container } = renderComponent(defaultExperiment)

            // Click pencil button to enable custom split editing
            const customizeButton = screen.getByRole('button', { name: /customize split/i })
            await userEvent.click(customizeButton)

            const percentageInputs = container.querySelectorAll(
                '[data-attr="experiment-variant-rollout-percentage-input"]'
            )

            await userEvent.clear(percentageInputs[0] as Element)
            await userEvent.type(percentageInputs[0] as Element, '70')

            // Check the last call
            const lastCall = mockOnChange.mock.calls[mockOnChange.mock.calls.length - 1]
            expect(lastCall[0]).toEqual(
                expect.objectContaining({
                    parameters: expect.objectContaining({
                        feature_flag_variants: expect.arrayContaining([
                            expect.objectContaining({ key: 'control', rollout_percentage: 70 }),
                        ]),
                    }),
                })
            )
        })

        it('shows error when percentages do not sum to 100', () => {
            const invalidExperiment = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 40 },
                        { key: 'test', rollout_percentage: 40 },
                    ],
                },
            }

            renderComponent(invalidExperiment)

            expect(screen.getByText(/must sum to 100 \(currently 80\)/i)).toBeInTheDocument()
        })

        it('removes variant when clicking delete button', async () => {
            const experimentWithThreeVariants = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'test', rollout_percentage: 33 },
                        { key: 'test-2', rollout_percentage: 34 },
                    ],
                },
            }

            const { container } = renderComponent(experimentWithThreeVariants)

            const deleteButtons = container.querySelectorAll('[data-attr^="delete-prop-filter"]')

            // Click the first delete button (which is for the second variant, since control has no delete button)
            await userEvent.click(deleteButtons[0] as Element)

            expect(mockOnChange).toHaveBeenCalledWith({
                parameters: expect.objectContaining({
                    feature_flag_variants: expect.arrayContaining([
                        expect.objectContaining({ key: 'control' }),
                        expect.objectContaining({ key: 'test-2' }),
                    ]),
                }),
            })
        })

        it('does not show delete button for control variant', () => {
            const experimentWithThreeVariants = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'test', rollout_percentage: 33 },
                        { key: 'test-2', rollout_percentage: 34 },
                    ],
                },
            }

            const { container } = render(
                <VariantsPanelCreateFeatureFlag experiment={experimentWithThreeVariants} onChange={mockOnChange} />
            )

            const rows = container.querySelectorAll('tbody tr')
            const controlRow = rows[0] // First row (control variant)

            // Control variant should not have a delete button
            const deleteButton = controlRow.querySelector('[data-attr^="delete-prop-filter"]')
            expect(deleteButton).not.toBeInTheDocument()
        })
    })

    describe('rollout distribution', () => {
        it('redistributes percentages equally when clicking balance button', async () => {
            const unevenExperiment = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 20 },
                        { key: 'test', rollout_percentage: 80 },
                    ],
                },
            }

            renderComponent(unevenExperiment)

            const balanceButton = screen.getByRole('button', { name: /distribute split evenly/i })
            await userEvent.click(balanceButton)

            expect(mockOnChange).toHaveBeenCalledWith({
                parameters: expect.objectContaining({
                    feature_flag_variants: [
                        expect.objectContaining({ key: 'control', rollout_percentage: 50 }),
                        expect.objectContaining({ key: 'test', rollout_percentage: 50 }),
                    ],
                }),
            })
        })
    })

    describe('experience continuity', () => {
        it('toggles experience continuity checkbox', async () => {
            renderComponent(defaultExperiment)

            const checkbox = screen.getByRole('checkbox')
            await userEvent.click(checkbox)

            expect(mockOnChange).toHaveBeenCalledWith({
                parameters: expect.objectContaining({
                    ensure_experience_continuity: true,
                }),
            })
        })

        it('defaults to unchecked', () => {
            renderComponent(defaultExperiment)

            const checkbox = screen.getByRole('checkbox') as HTMLInputElement
            expect(checkbox.checked).toBe(false)
        })
    })

    describe('edge cases', () => {
        it('handles experiment without parameters', () => {
            const experimentWithoutParams = {
                ...NEW_EXPERIMENT,
                name: 'Test',
                feature_flag_key: '',
            }

            renderComponent(experimentWithoutParams)

            // Should render with default variants
            expect(screen.getByDisplayValue('control')).toBeInTheDocument()
            expect(screen.getByDisplayValue('test')).toBeInTheDocument()
        })

        it('prevents adding more than maximum variants', async () => {
            const maxVariants = Array.from({ length: MAX_EXPERIMENT_VARIANTS }, (_, i) => ({
                key: `variant-${i}`,
                rollout_percentage: 5,
            }))

            const experimentWithMaxVariants = {
                ...defaultExperiment,
                parameters: {
                    feature_flag_variants: maxVariants,
                },
            }

            renderComponent(experimentWithMaxVariants)

            const addButton = screen.queryByRole('button', { name: /add variant/i })
            expect(addButton).not.toBeInTheDocument()
        })
    })
})
