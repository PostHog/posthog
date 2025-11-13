import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { PropertyFilterValue } from '~/types'

import type { propertyFilterBetweenLogicType } from './propertyFilterBetweenLogicType'

export interface PropertyFilterBetweenLogicProps {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
}

function parseNumericValue(value: PropertyFilterValue, index: number): number | null {
    const valueAtIndex = Array.isArray(value) ? value[index] : null
    const numValue = Number(valueAtIndex)
    return Number.isNaN(numValue) || valueAtIndex === null ? null : numValue
}

function handleValueChange(
    minValue: number | null,
    maxValue: number | null,
    onSet: (value: PropertyFilterValue) => void
): void {
    if (minValue === null || maxValue === null) {
        onSet(null)
    } else if (minValue <= maxValue) {
        onSet([minValue, maxValue])
    }
}

export const propertyFilterBetweenLogic = kea<propertyFilterBetweenLogicType>([
    props({} as PropertyFilterBetweenLogicProps),
    key((props) => JSON.stringify(props.value)),
    path(['lib', 'components', 'PropertyFilters', 'components', 'propertyFilterBetweenLogic']),
    actions({
        setLocalMin: (value: number | null) => ({ value }),
        setLocalMax: (value: number | null) => ({ value }),
    }),
    reducers(({ props }) => ({
        localMin: [
            parseNumericValue(props.value, 0),
            {
                setLocalMin: (_, { value }) => value,
            },
        ],
        localMax: [
            parseNumericValue(props.value, 1),
            {
                setLocalMax: (_, { value }) => value,
            },
        ],
    })),
    selectors({
        errorMessage: [
            (s) => [s.localMin, s.localMax],
            (localMin, localMax): string | null => {
                if (localMin != null && localMax != null && localMin > localMax) {
                    return 'Min must be less than or equal to max'
                }
                return null
            },
        ],
    }),
    listeners(({ values, props }) => ({
        setLocalMin: ({ value }) => handleValueChange(value, values.localMax, props.onSet),
        setLocalMax: ({ value }) => handleValueChange(values.localMin, value, props.onSet),
    })),
])
