import React, { useState } from 'react'
import { LemonButtonWithPopupProps } from '../LemonButton'
import { TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { SearchDefinitionTypes, UniversalSearchGroupType } from './types'
import { Popup } from 'lib/components/Popup/Popup'
import { UniversalSearch } from './UniversalSearch'
import { Button } from 'antd'
import { DownOutlined } from '@ant-design/icons'
import { combineUrl, router } from 'kea-router'
import clsx from 'clsx'
import { urls } from 'scenes/urls'
import { ActionType, ChartDisplayType, Group, InsightModel, InsightType } from '~/types'
import { PluginSelectionType } from 'scenes/plugins/pluginsLogic'

export interface UniversalSearchPopupProps<ValueType = TaxonomicFilterValue>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'value' | 'onChange' | 'placeholder'> {
    groupType: UniversalSearchGroupType
    value?: ValueType
    onChange?: (value: ValueType, groupType: UniversalSearchGroupType, item: SearchDefinitionTypes) => void
    groupTypes?: UniversalSearchGroupType[]
    renderValue?: (value: ValueType) => JSX.Element
    dataAttr?: string
    placeholder?: React.ReactNode
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
}

function redirectOnSelectItems(
    value: TaxonomicFilterValue,
    groupType: UniversalSearchGroupType,
    item: SearchDefinitionTypes
): void {
    if (groupType === UniversalSearchGroupType.Events) {
        router.actions.push(
            combineUrl(
                urls.insightNew({
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    display: ChartDisplayType.ActionsLineGraph,
                    events: [{ id: value, name: value, type: 'events', math: 'dau' }],
                })
            ).url
        )
    } else if (groupType === UniversalSearchGroupType.Actions) {
        router.actions.push(
            combineUrl(
                urls.insightNew({
                    insight: InsightType.TRENDS,
                    interval: 'day',
                    display: ChartDisplayType.ActionsLineGraph,
                    actions: [
                        {
                            id: (item as ActionType).id,
                            name: (item as ActionType).name,
                            type: 'actions',
                            order: 0,
                        },
                    ],
                })
            ).url
        )
    } else if (groupType === UniversalSearchGroupType.Cohorts) {
        router.actions.push(urls.cohort(value))
    } else if (groupType === UniversalSearchGroupType.Persons) {
        router.actions.push(urls.person(String(value)))
    } else if (groupType.startsWith(UniversalSearchGroupType.GroupsPrefix)) {
        router.actions.push(urls.group((item as Group).group_type_index, String(value)))
    } else if (groupType === UniversalSearchGroupType.Insights) {
        router.actions.push(urls.insightView((item as InsightModel).short_id))
    } else if (groupType === UniversalSearchGroupType.FeatureFlags) {
        router.actions.push(urls.featureFlag(value))
    } else if (groupType === UniversalSearchGroupType.Experiments) {
        router.actions.push(urls.experiment(value))
    } else if (groupType === UniversalSearchGroupType.Plugins) {
        router.actions.push(
            combineUrl(urls.plugins(), {
                tab: (item as PluginSelectionType).tab,
                name: (item as PluginSelectionType).name,
            }).url
        )
    } else if (groupType === UniversalSearchGroupType.Dashboards) {
        router.actions.push(urls.dashboard(value))
    }
}

export function UniversalSearchPopup({
    groupType,
    value,
    onChange,
    renderValue,
    groupTypes,
    dataAttr,
    placeholder = 'Please select',
    style,
    fullWidth = true,
}: UniversalSearchPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popup
            overlay={
                <UniversalSearch
                    groupType={groupType}
                    value={value}
                    onChange={({ type }, payload, item) => {
                        redirectOnSelectItems(payload, type, item)
                        onChange?.(payload, type, item)
                        setVisible(false)
                    }}
                    searchGroupTypes={groupTypes ?? [groupType]}
                />
            }
            visible={visible}
            onClickOutside={() => setVisible(false)}
        >
            {({ setRef }) => (
                <Button
                    data-attr={dataAttr}
                    onClick={() => setVisible(!visible)}
                    ref={setRef}
                    className={clsx('TaxonomicPopup__button', { 'full-width': fullWidth })}
                    style={style}
                >
                    <span className="text-overflow" style={{ maxWidth: '100%' }}>
                        {value ? renderValue?.(value) ?? String(value) : <em>{placeholder}</em>}
                    </span>
                    <div style={{ flexGrow: 1 }} />
                    <DownOutlined style={{ fontSize: 10 }} />
                </Button>
            )}
        </Popup>
    )
}
