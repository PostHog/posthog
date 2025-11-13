import { useActions, useValues } from 'kea'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue } from '~/types'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

export interface PropertyFilterBetweenProps {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
}

export function PropertyFilterBetween({ value, onSet, size }: PropertyFilterBetweenProps): JSX.Element {
    const logic = propertyFilterBetweenLogic({ value, onSet })
    const { localMin, localMax, errorMessage } = useValues(logic)
    const { setLocalMin, setLocalMax } = useActions(logic)

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={localMin ?? undefined}
                data-attr="prop-val"
                onChange={(value) => setLocalMin(value ?? null)}
                placeholder="min"
                size={size}
                status={errorMessage ? 'danger' : undefined}
            />
            <span className="font-medium">and</span>
            <LemonInput
                type="number"
                value={localMax ?? undefined}
                data-attr="prop-val"
                onChange={(value) => setLocalMax(value ?? null)}
                placeholder="max"
                size={size}
                status={errorMessage ? 'danger' : undefined}
            />
            {errorMessage && <span className="text-danger text-xs">{errorMessage}</span>}
        </div>
    )
}
