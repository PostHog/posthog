import { computeComparisonDisplay } from './BoldNumber'

describe('computeComparisonDisplay', () => {
    const finiteCases: {
        name: string
        currentValue: number | null
        previousValue: number | null
        expectedHasComparableDiff: boolean
        expectedDisplayText: string
        expectedPercentageDiff: number
    }[] = [
        // Normal cases
        {
            name: 'positive diff (doubled)',
            currentValue: 200,
            previousValue: 100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Up 100% from',
            expectedPercentageDiff: 1,
        },
        {
            name: 'negative diff (halved)',
            currentValue: 50,
            previousValue: 100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Down 50% from',
            expectedPercentageDiff: -0.5,
        },
        {
            name: 'zero diff (no change)',
            currentValue: 100,
            previousValue: 100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'No change from',
            expectedPercentageDiff: 0,
        },
        // Edge cases
        {
            name: 'large values',
            currentValue: 1_000_000,
            previousValue: 500_000,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Up 100% from',
            expectedPercentageDiff: 1,
        },
        {
            name: 'small fractional diff',
            currentValue: 100.01,
            previousValue: 100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Up 0.01% from',
            expectedPercentageDiff: 0.0001,
        },
        {
            name: 'negative previous with increase',
            currentValue: -50,
            previousValue: -100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Up 50% from',
            expectedPercentageDiff: 0.5,
        },
        {
            name: 'negative previous with decrease',
            currentValue: -150,
            previousValue: -100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Down 50% from',
            expectedPercentageDiff: -0.5,
        },
        {
            name: 'current is 0, previous is non-zero',
            currentValue: 0,
            previousValue: 100,
            expectedHasComparableDiff: true,
            expectedDisplayText: 'Down 100% from',
            expectedPercentageDiff: -1,
        },
    ]

    finiteCases.forEach(
        ({
            name,
            currentValue,
            previousValue,
            expectedHasComparableDiff,
            expectedDisplayText,
            expectedPercentageDiff,
        }) => {
            it(name, () => {
                const { hasComparableDiff, displayText, percentageDiff } = computeComparisonDisplay(
                    currentValue,
                    previousValue
                )

                expect(hasComparableDiff).toBe(expectedHasComparableDiff)
                expect(displayText).toBe(expectedDisplayText)
                expect(percentageDiff).toBeCloseTo(expectedPercentageDiff, 4)
            })
        }
    )

    const nullCases: {
        name: string
        currentValue: number | null
        previousValue: number | null
    }[] = [
        { name: 'previous is null', currentValue: 100, previousValue: null },
        { name: 'current is null', currentValue: null, previousValue: 100 },
        { name: 'both null', currentValue: null, previousValue: null },
    ]

    nullCases.forEach(({ name, currentValue, previousValue }) => {
        it(name, () => {
            const { hasComparableDiff, displayText, percentageDiff } = computeComparisonDisplay(
                currentValue,
                previousValue
            )
            expect(hasComparableDiff).toBe(false)
            expect(displayText).toBe('No data in the')
            expect(percentageDiff).toBeNull()
        })
    })

    const nonFiniteCases: {
        name: string
        currentValue: number
        previousValue: number
    }[] = [
        { name: 'previous is 0 (division by zero)', currentValue: 100, previousValue: 0 },
        { name: 'both are 0 (0/0 → NaN)', currentValue: 0, previousValue: 0 },
    ]

    nonFiniteCases.forEach(({ name, currentValue, previousValue }) => {
        it(name, () => {
            const result = computeComparisonDisplay(currentValue, previousValue)
            expect(result.hasComparableDiff).toBe(false)
            expect(result.displayText).toBe('No data in the')
            expect(Number.isFinite(result.percentageDiff)).toBe(false)
        })
    })
})
