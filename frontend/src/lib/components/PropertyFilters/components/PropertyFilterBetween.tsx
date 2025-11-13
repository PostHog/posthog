import { useEffect, useState } from 'react'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue } from '~/types'

export interface PropertyFilterBetweenProps {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
}

export function PropertyFilterBetween({ value, onSet, size }: PropertyFilterBetweenProps): JSX.Element {
    const [minValue, maxValue] = Array.isArray(value) ? value : [undefined, undefined]
    const [localMin, setLocalMin] = useState<number | undefined>(
        Number.isNaN(Number(minValue)) ? undefined : Number(minValue)
    )
    const [localMax, setLocalMax] = useState<number | undefined>(
        Number.isNaN(Number(maxValue)) ? undefined : Number(maxValue)
    )
    const [errorMessage, setErrorMessage] = useState<string | null>(null)

    useEffect(() => {
        if (localMin !== undefined && localMax !== undefined && localMin >= localMax) {
            setErrorMessage('Min must be less than max')
        } else {
            setErrorMessage(null)
        }
    }, [localMin, localMax])

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={localMin}
                data-attr="prop-val"
                onChange={(val) => {
                    setLocalMin(val)
                    onSet(localMax === undefined || val === undefined ? null : [val, localMax])
                }}
                placeholder="min"
                size={size}
                status={errorMessage ? 'danger' : undefined}
            />
            <span className="font-medium">and</span>
            <LemonInput
                type="number"
                value={localMax}
                data-attr="prop-val"
                onChange={(val) => {
                    setLocalMax(val)
                    onSet(localMin === undefined || val === undefined ? null : [localMin, val])
                }}
                placeholder="max"
                size={size}
                status={errorMessage ? 'danger' : undefined}
            />
            {errorMessage && <span className="text-danger text-xs">{errorMessage}</span>}
        </div>
    )
}
