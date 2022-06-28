import { useActions } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import React from 'react'
import { EditorFilterProps } from '~/types'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

const INSIGHT_TYPE_OPTIONS: LemonSelectOptions = Object.entries(INSIGHT_TYPES_METADATA).reduce((acc, [key, meta]) => {
    return {
        ...acc,
        [key]: {
            label: meta.name,
            icon: meta.icon ? <meta.icon color="#747EA2" noBackground /> : null,
        },
    }
}, {})

export function InsightTypeSelector({ value }: EditorFilterProps): JSX.Element {
    const { setActiveView } = useActions(insightLogic)

    return (
        <LemonSelect
            options={INSIGHT_TYPE_OPTIONS}
            value={value}
            onChange={(v: any): void => {
                if (v) {
                    setActiveView(v)
                }
            }}
            type="stealth"
            outlined
            fullWidth
            data-attr="insight-type"
        />
    )
}
