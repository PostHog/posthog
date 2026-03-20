import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, type RenderResult, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    computeUpdatedVariantSplit,
    distributeVariantsEvenly,
    VariantDistributionEditor,
} from './VariantDistributionEditor'

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

describe('VariantDistributionEditor', () => {
    describe('computeUpdatedVariantSplit', () => {
        it.each([
            { value: 70, expectedControl: 70, expectedTest: 30 },
            { value: 0, expectedControl: 0, expectedTest: 100 },
            { value: 100, expectedControl: 100, expectedTest: 0 },
        ])(
            'auto-completes other variant to $expectedTest% when first is set to $expectedControl% with 2 variants',
            ({ value, expectedControl, expectedTest }) => {
                const variants = [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ]
                const result = computeUpdatedVariantSplit(variants, 0, value)
                expect(result[0].rollout_percentage).toBe(expectedControl)
                expect(result[1].rollout_percentage).toBe(expectedTest)
            }
        )

        it('does not auto-complete other variants with 3+ variants', () => {
            const variants = [
                { key: 'control', rollout_percentage: 34 },
                { key: 'test', rollout_percentage: 33 },
                { key: 'test-2', rollout_percentage: 33 },
            ]
            const result = computeUpdatedVariantSplit(variants, 0, 10)
            expect(result[0].rollout_percentage).toBe(10)
            expect(result[1].rollout_percentage).toBe(33)
            expect(result[2].rollout_percentage).toBe(33)
        })

        it('caps value to 0-100 range', () => {
            const variants = [
                { key: 'control', rollout_percentage: 50 },
                { key: 'test', rollout_percentage: 50 },
            ]
            expect(computeUpdatedVariantSplit(variants, 0, 150)[0].rollout_percentage).toBe(100)
            expect(computeUpdatedVariantSplit(variants, 0, -10)[0].rollout_percentage).toBe(0)
        })

        it('does not mutate the original array', () => {
            const variants = [
                { key: 'control', rollout_percentage: 50 },
                { key: 'test', rollout_percentage: 50 },
            ]
            const result = computeUpdatedVariantSplit(variants, 0, 70)
            expect(variants[0].rollout_percentage).toBe(50)
            expect(result).not.toBe(variants)
        })
    })

    describe('distributeVariantsEvenly', () => {
        it('distributes evenly for 2 variants', () => {
            const variants = [
                { key: 'control', rollout_percentage: 0 },
                { key: 'test', rollout_percentage: 0 },
            ]
            const result = distributeVariantsEvenly(variants)
            expect(result[0].rollout_percentage).toBe(50)
            expect(result[1].rollout_percentage).toBe(50)
        })

        it('distributes with remainder for 3 variants', () => {
            const variants = [
                { key: 'control', rollout_percentage: 0 },
                { key: 'test', rollout_percentage: 0 },
                { key: 'test-2', rollout_percentage: 0 },
            ]
            const result = distributeVariantsEvenly(variants)
            const sum = result.reduce((s, v) => s + v.rollout_percentage, 0)
            expect(sum).toBe(100)
            // First variant gets the extra 1%
            expect(result[0].rollout_percentage).toBe(34)
            expect(result[1].rollout_percentage).toBe(33)
            expect(result[2].rollout_percentage).toBe(33)
        })

        it('does not mutate the original array', () => {
            const variants = [
                { key: 'control', rollout_percentage: 0 },
                { key: 'test', rollout_percentage: 0 },
            ]
            const result = distributeVariantsEvenly(variants)
            expect(variants[0].rollout_percentage).toBe(0)
            expect(result).not.toBe(variants)
        })
    })

    describe('component', () => {
        const mockOnVariantsChange = jest.fn()

        const defaultVariants = [
            { key: 'control', rollout_percentage: 50 },
            { key: 'test', rollout_percentage: 50 },
        ]

        const renderEditor = (variants = defaultVariants, rolloutPercentage = 100): RenderResult => {
            return render(
                <VariantDistributionEditor
                    variants={variants}
                    onVariantsChange={mockOnVariantsChange}
                    rolloutPercentage={rolloutPercentage}
                />
            )
        }

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/feature_flags/': () => [200, { results: [], count: 0 }],
                    '/api/projects/:team_id/experiments': () => [200, { results: [], count: 0 }],
                },
            })
            initKeaTests()
            jest.clearAllMocks()
        })

        afterEach(() => {
            cleanup()
        })

        it('renders variant keys and split inputs', () => {
            renderEditor()
            expect(screen.getByText('control')).toBeInTheDocument()
            expect(screen.getByText('test')).toBeInTheDocument()
            expect(screen.getByText('Variant distribution')).toBeInTheDocument()
        })

        it('renders traffic preview', () => {
            renderEditor()
            expect(screen.getByText('Traffic preview')).toBeInTheDocument()
        })

        it('does not show "Add variant" button', () => {
            renderEditor()
            expect(screen.queryByRole('button', { name: /add variant/i })).not.toBeInTheDocument()
        })

        it('does not show pencil icon (customize split toggle)', () => {
            renderEditor()
            expect(screen.queryByRole('button', { name: /customize split/i })).not.toBeInTheDocument()
        })

        it('does not show rollout percentage slider', () => {
            renderEditor()
            expect(screen.queryByRole('slider')).not.toBeInTheDocument()
            expect(screen.queryByText('Rollout percent')).not.toBeInTheDocument()
        })

        it('does not show "Persist flag across authentication steps" checkbox', () => {
            renderEditor()
            expect(screen.queryByText(/persist flag/i)).not.toBeInTheDocument()
            expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
        })

        it('split inputs are always editable without a toggle', () => {
            const { container } = renderEditor()
            const inputs = container.querySelectorAll('input[type="number"]')
            expect(inputs.length).toBe(2)
            inputs.forEach((input) => {
                expect(input).not.toBeDisabled()
            })
        })

        it('shows validation error when splits do not sum to 100', () => {
            const invalidVariants = [
                { key: 'control', rollout_percentage: 40 },
                { key: 'test', rollout_percentage: 40 },
            ]
            renderEditor(invalidVariants)
            expect(screen.getByText(/must sum to 100 \(currently 80\)/i)).toBeInTheDocument()
        })

        it('calls onVariantsChange with auto-completed split for 2 variants', async () => {
            const { container } = renderEditor()
            const inputs = container.querySelectorAll('input[type="number"]')

            await fireEvent.change(inputs[0], { target: { value: '70' } })

            const lastCall = mockOnVariantsChange.mock.calls[mockOnVariantsChange.mock.calls.length - 1][0]
            expect(lastCall).toEqual([
                expect.objectContaining({ key: 'control', rollout_percentage: 70 }),
                expect.objectContaining({ key: 'test', rollout_percentage: 30 }),
            ])
        })

        it('shows "Distribute evenly" button when splits are uneven', () => {
            const unevenVariants = [
                { key: 'control', rollout_percentage: 20 },
                { key: 'test', rollout_percentage: 80 },
            ]
            renderEditor(unevenVariants)
            const button = screen.getByText('Distribute evenly').closest('button')!
            expect(button).toBeVisible()
        })

        it('hides "Distribute evenly" button when splits are already even', () => {
            renderEditor()
            const button = screen.getByText('Distribute evenly').closest('button')!
            expect(button).toHaveClass('invisible')
        })

        it('calls onVariantsChange with even distribution when clicking "Distribute evenly"', async () => {
            const unevenVariants = [
                { key: 'control', rollout_percentage: 20 },
                { key: 'test', rollout_percentage: 80 },
            ]
            renderEditor(unevenVariants)

            await userEvent.click(screen.getByText('Distribute evenly').closest('button')!)

            expect(mockOnVariantsChange).toHaveBeenCalledWith([
                expect.objectContaining({ key: 'control', rollout_percentage: 50 }),
                expect.objectContaining({ key: 'test', rollout_percentage: 50 }),
            ])
        })

        it('shows "Not released" indicator when rollout is less than 100%', () => {
            renderEditor(defaultVariants, 60)
            expect(screen.getByText(/not released to 40%/i)).toBeInTheDocument()
        })

        it('does not show "Not released" indicator at 100% rollout', () => {
            renderEditor(defaultVariants, 100)
            expect(screen.queryByText(/not released/i)).not.toBeInTheDocument()
        })
    })
})
