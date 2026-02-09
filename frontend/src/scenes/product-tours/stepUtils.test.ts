import { ProductTourStep } from '~/types'

import { hasElementTarget, hasIncompleteTargeting, normalizeStep, prepareStepForSave } from './stepUtils'

const baseStep: ProductTourStep = {
    id: 'step-1',
    type: 'modal',
    content: null,
}

describe('stepUtils', () => {
    describe('normalizeStep', () => {
        it.each<{ name: string; input: Partial<ProductTourStep>; expected: Partial<ProductTourStep> }>([
            {
                name: 'keeps existing elementTargeting',
                input: { elementTargeting: 'manual' },
                expected: { elementTargeting: 'manual' },
            },
            {
                name: 'derives manual from useManualSelector=true',
                input: { useManualSelector: true, selector: '.foo' },
                expected: { elementTargeting: 'manual', useManualSelector: true },
            },
            {
                name: 'derives auto from inferenceData',
                input: { inferenceData: { selector: '.bar' } as any },
                expected: { elementTargeting: 'auto' },
            },
            {
                name: 'converts type=element to auto + modal',
                input: { type: 'element' as any },
                expected: { elementTargeting: 'auto', type: 'modal' },
            },
            {
                name: 'leaves plain modal step unchanged',
                input: {},
                expected: {},
            },
            {
                name: 'prefers useManualSelector over inferenceData',
                input: { useManualSelector: true, inferenceData: { selector: '.x' } as any },
                expected: { elementTargeting: 'manual', useManualSelector: true },
            },
        ])('$name', ({ input, expected }) => {
            const step = { ...baseStep, ...input }
            const result = normalizeStep(step)

            for (const [key, value] of Object.entries(expected)) {
                expect(result[key as keyof ProductTourStep]).toEqual(value)
            }
            if (!('elementTargeting' in expected)) {
                expect(result.elementTargeting).toBeUndefined()
            }
        })
    })

    describe('prepareStepForSave', () => {
        it.each<{
            name: string
            elementTargeting: ProductTourStep['elementTargeting']
            expectedUseManualSelector: boolean | undefined
        }>([
            {
                name: 'manual → useManualSelector=true',
                elementTargeting: 'manual',
                expectedUseManualSelector: true,
            },
            {
                name: 'auto → useManualSelector=undefined',
                elementTargeting: 'auto',
                expectedUseManualSelector: undefined,
            },
            {
                name: 'undefined → useManualSelector=undefined',
                elementTargeting: undefined,
                expectedUseManualSelector: undefined,
            },
        ])('$name', ({ elementTargeting, expectedUseManualSelector }) => {
            const step = { ...baseStep, elementTargeting }
            const result = prepareStepForSave(step)
            expect(result.useManualSelector).toBe(expectedUseManualSelector)
        })
    })

    describe('hasElementTarget', () => {
        it.each<{ name: string; input: Partial<ProductTourStep>; expected: boolean }>([
            {
                name: 'manual mode with selector → true',
                input: { elementTargeting: 'manual', selector: '.foo' },
                expected: true,
            },
            {
                name: 'manual mode without selector → false',
                input: { elementTargeting: 'manual' },
                expected: false,
            },
            {
                name: 'auto mode with inferenceData → true',
                input: { elementTargeting: 'auto', inferenceData: { selector: '.bar' } as any },
                expected: true,
            },
            {
                name: 'auto mode without inferenceData → false',
                input: { elementTargeting: 'auto' },
                expected: false,
            },
            {
                name: 'no targeting with inferenceData → true',
                input: { inferenceData: { selector: '.baz' } as any },
                expected: true,
            },
            {
                name: 'no targeting, no data → false',
                input: {},
                expected: false,
            },
        ])('$name', ({ input, expected }) => {
            const step = { ...baseStep, ...input }
            expect(hasElementTarget(step)).toBe(expected)
        })
    })

    describe('hasIncompleteTargeting', () => {
        it.each<{ name: string; input: Partial<ProductTourStep>; expected: boolean }>([
            {
                name: 'auto mode, no data → incomplete',
                input: { elementTargeting: 'auto' },
                expected: true,
            },
            {
                name: 'auto mode, has inferenceData → complete',
                input: { elementTargeting: 'auto', inferenceData: { selector: '.x' } as any },
                expected: false,
            },
            {
                name: 'manual mode, no selector → incomplete',
                input: { elementTargeting: 'manual' },
                expected: true,
            },
            {
                name: 'manual mode, has selector → complete',
                input: { elementTargeting: 'manual', selector: '.foo' },
                expected: false,
            },
            {
                name: 'no targeting → not incomplete',
                input: {},
                expected: false,
            },
        ])('$name', ({ input, expected }) => {
            const step = { ...baseStep, ...input }
            expect(hasIncompleteTargeting(step)).toBe(expected)
        })
    })
})
