import { useActions } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Select } from 'antd'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import React from 'react'
import { EditorFilterProps } from '~/types'

export function EFInsightType({ value }: EditorFilterProps): JSX.Element {
    const { setActiveView } = useActions(insightLogic)
    return (
        <Select value={value} onChange={(v): void => setActiveView(v)} dropdownMatchSelectWidth={false}>
            {Object.entries(INSIGHT_TYPES_METADATA).map(([type, meta], index) => (
                <Select.Option key={index} value={type}>
                    <div className="insight-type-icon-wrapper">
                        {meta.icon ? (
                            <div className="icon-container">
                                <div className="icon-container-inner">
                                    <meta.icon color="#747EA2" noBackground />
                                </div>
                            </div>
                        ) : null}
                        <div>{meta.name}</div>
                    </div>
                </Select.Option>
            ))}
        </Select>
    )
}
