import React from 'react'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useActions, useValues } from 'kea'
import { intervals } from 'lib/components/IntervalFilter/intervals'
import { InsightType, IntervalType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'

interface InvertalFilterProps {
    view: InsightType
    disabled?: boolean
}

export function IntervalFilter({ disabled }: InvertalFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { interval } = useValues(intervalFilterLogic(insightProps))
    const { setInterval } = useActions(intervalFilterLogic(insightProps))
    return (
        <LemonSelect
            size={'small'}
            disabled={disabled}
            value={interval || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(value) => {
                if (value) {
                    setInterval(String(value) as IntervalType)
                }
            }}
            data-attr="interval-filter"
            options={Object.entries(intervals).map(([value, { label }]) => ({ value, label }))}
        />
    )
}
