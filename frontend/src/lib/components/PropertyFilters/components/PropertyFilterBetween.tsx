import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue } from '~/types'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

export interface PropertyFilterBetweenProps {
    logicKey?: string
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
}

let uniqueMemoizedIndex = 0
const usePropertyFilterBetweenLogic = (
    props: PropertyFilterBetweenProps
): ReturnType<typeof propertyFilterBetweenLogic.build> => {
    const logicKey = useMemo(() => props.logicKey || `prop-filter-between-${uniqueMemoizedIndex++}`, [props.logicKey])
    return propertyFilterBetweenLogic({ ...props, key: logicKey })
}

export function PropertyFilterBetween({ logicKey, value, onSet, size }: PropertyFilterBetweenProps): JSX.Element {
    const logic = usePropertyFilterBetweenLogic({ logicKey, value, onSet, size })
    const { localMin, localMax } = useValues(logic)
    const { setLocalMin, setLocalMax } = useActions(logic)

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={localMin ?? undefined}
                data-attr="prop-val-min"
                aria-label="Minimum value"
                onChange={(value) => setLocalMin(value ?? null)}
                placeholder="min"
                size={size}
            />
            <span className="font-medium">and</span>
            <LemonInput
                type="number"
                value={localMax ?? undefined}
                data-attr="prop-val-max"
                aria-label="Maximum value"
                onChange={(value) => setLocalMax(value ?? null)}
                placeholder="max"
                size={size}
            />
        </div>
    )
}
