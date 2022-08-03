import React from 'react'
import { intervalFilterLogic } from './intervalFilterLogic'
import { useValues, useActions } from 'kea'
import { intervals } from 'lib/components/IntervalFilter/intervals'
import { IntervalType, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

interface InvertalFilterProps {
    view: InsightType
    disabled?: boolean
}

export function IntervalFilter({ disabled }: InvertalFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { interval } = useValues(intervalFilterLogic(insightProps))
    const { setInterval } = useActions(intervalFilterLogic(insightProps))
    const options: LemonSelectOptions = Object.entries(intervals).reduce((result, [key, { label }]) => {
        result[key] = { label }
        return result
    }, {})
    return (
        <LemonSelect
            size={'small'}
            status="stealth"
            outlined
            disabled={disabled}
            value={interval || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(value) => {
                if (value) {
                    setInterval(String(value) as IntervalType)
                }
            }}
            data-attr="interval-filter"
            options={options}
        />
    )
}
