import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isTrendsQuery } from '~/queries/utils'
import { useDebouncedCallback } from 'use-debounce'
import { useState, useEffect } from 'react'

export function ConfidenceLevelInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { confidenceLevel } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const trendsFilter = isTrendsQuery(querySource) ? querySource.trendsFilter : undefined

    const [localValue, setLocalValue] = useState(confidenceLevel)

    useEffect(() => {
        setLocalValue(confidenceLevel)
    }, [confidenceLevel])

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        if (isTrendsQuery(querySource)) {
            const newQuery = { ...querySource }
            newQuery.trendsFilter = { ...trendsFilter, confidence_level: value }
            updateQuerySource(newQuery)
        }
    }, 500)

    return (
        <div className="flex items-center justify-between w-full min-h-8 px-2 pb-2">
            <span>Confidence level</span>
            <LemonInput
                type="number"
                min={0}
                max={100}
                step={1}
                value={localValue}
                onChange={(value) => {
                    const numValue = value ?? 95
                    setLocalValue(numValue)
                    debouncedUpdate(numValue)
                }}
                suffix={<span>%</span>}
                size="small"
                className="w-20"
            />
        </div>
    )
}
