import React, { useState } from 'react'
import { LemonButtonWithPopupProps } from '../LemonButton'
import { TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { SearchDefinitionTypes, UniversalSearchGroupType, UniversalSearchProps } from './types'
import { Popup } from 'lib/components/Popup/Popup'
import { UniversalSearch } from './UniversalSearch'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import { ActionType, ChartDisplayType, Group, InsightModel, InsightType } from '~/types'
import { PluginSelectionType } from 'scenes/plugins/pluginsLogic'
import clsx from 'clsx'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { useValues } from 'kea'
import { universalSearchLogic } from './universalSearchLogic'
import { IconMagnifier } from '../icons'
import { Input } from 'antd'

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
    groupTypes,
    dataAttr,
    style,
    fullWidth = true,
}: UniversalSearchPopupProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    const { isSideBarShown } = useValues(navigationLogic)
    const universalSearchLogicProps: UniversalSearchProps = {
        groupType,
        value,
        onChange: ({ type }, payload, item) => {
            redirectOnSelectItems(payload, type, item)
            onChange?.(payload, type, item)
            setVisible(false)
        },
        searchGroupTypes: groupTypes ?? [groupType],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
    }
    const logic = universalSearchLogic(universalSearchLogicProps)
    const { searchQuery, searchPlaceholder } = useValues(logic)

    return (
        <div className="universal-search">
            <Popup
                overlay={
                    <UniversalSearch groupType={groupType} value={value} searchGroupTypes={groupTypes ?? [groupType]} />
                }
                visible={visible}
                placement="right-start"
                fallbackPlacements={['bottom']}
                onClickOutside={() => setVisible(false)}
                modifier={{
                    name: 'offset',
                    options: {
                        offset: ({ placement }) => {
                            if (placement === 'right-start') {
                                return [-10, -249 - 243]
                            } else {
                                return []
                            }
                        },
                    },
                }}
            >
                {({ setRef }) => (
                    <div
                        data-attr={dataAttr}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            setVisible(!visible)
                        }}
                        ref={setRef}
                        className={clsx(
                            { 'full-width': fullWidth },
                            '',
                            'SearchBox',
                            isSideBarShown && 'SearchBox--sidebar-shown'
                        )}
                        style={style}
                    >
                        <Input
                            style={{ flexGrow: 1, cursor: 'pointer', opacity: visible ? '0' : '1' }}
                            data-attr="universal-search-field"
                            placeholder={searchPlaceholder}
                            value={searchQuery}
                            prefix={<IconMagnifier className={clsx('magnifier-icon', 'magnifier-icon-active222')} />}
                        />
                    </div>
                )}
            </Popup>
        </div>
    )
}
