import './UniversalSearch.scss'
import React, { useState } from 'react'
import { LemonButtonWithPopupProps } from '../LemonButton'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps, TaxonomicFilterValue } from '../TaxonomicFilter/types'
import { Popup } from 'lib/components/Popup/Popup'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import {
    ActionType,
    ChartDisplayType,
    CohortType,
    EventDefinition,
    Experiment,
    FeatureFlagType,
    Group,
    InsightModel,
    InsightType,
    PersonType,
} from '~/types'
import { PluginSelectionType } from 'scenes/plugins/pluginsLogic'
import clsx from 'clsx'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { useValues } from 'kea'
import { IconMagnifier } from '../icons'
import { Input } from 'antd'
import { useEventListener } from 'lib/hooks/useEventListener'
import { taxonomicFilterLogic } from '../TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'

export interface UniversalSearchPopupProps<ValueType = TaxonomicFilterValue>
    extends Omit<LemonButtonWithPopupProps, 'popup' | 'value' | 'onChange' | 'placeholder'> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType
    onChange?: (value: ValueType, groupType: TaxonomicFilterGroupType, item: SearchDefinitionTypes) => void
    groupTypes?: TaxonomicFilterGroupType[]
    renderValue?: (value: ValueType) => JSX.Element
    dataAttr?: string
    placeholder?: React.ReactNode
    dropdownMatchSelectWidth?: boolean
    allowClear?: boolean
}

type SearchDefinitionTypes =
    | EventDefinition
    | CohortType
    | ActionType
    | Experiment
    | PersonType
    | Group
    | FeatureFlagType
    | InsightModel
    | PluginSelectionType

function redirectOnSelectItems(
    value: TaxonomicFilterValue,
    groupType: TaxonomicFilterGroupType,
    item: SearchDefinitionTypes
): void {
    if (groupType === TaxonomicFilterGroupType.Events) {
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
    } else if (groupType === TaxonomicFilterGroupType.Actions) {
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
    } else if (groupType === TaxonomicFilterGroupType.Cohorts) {
        router.actions.push(urls.cohort(value))
    } else if (groupType === TaxonomicFilterGroupType.Persons) {
        router.actions.push(urls.person(String(value)))
    } else if (groupType.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)) {
        router.actions.push(urls.group((item as Group).group_type_index, String(value)))
    } else if (groupType === TaxonomicFilterGroupType.Insights) {
        router.actions.push(urls.insightView((item as InsightModel).short_id))
    } else if (groupType === TaxonomicFilterGroupType.FeatureFlags) {
        router.actions.push(urls.featureFlag(value))
    } else if (groupType === TaxonomicFilterGroupType.Experiments) {
        router.actions.push(urls.experiment(value))
    } else if (groupType === TaxonomicFilterGroupType.Plugins) {
        router.actions.push(
            combineUrl(urls.plugins(), {
                tab: (item as PluginSelectionType).tab,
                name: (item as PluginSelectionType).name,
            }).url
        )
    } else if (groupType === TaxonomicFilterGroupType.Dashboards) {
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
    const universalSearchLogicProps: TaxonomicFilterLogicProps = {
        groupType,
        value,
        onChange: ({ type }, payload, item) => {
            redirectOnSelectItems(payload, type, item)
            onChange?.(payload, type, item)
            setVisible(false)
        },
        taxonomicGroupTypes: groupTypes ?? [groupType],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'universalSearch',
    }
    const logic = taxonomicFilterLogic(universalSearchLogicProps)
    const { searchQuery, searchPlaceholder } = useValues(logic)

    // Command+S shortcut to get to universal search
    useEventListener('keydown', (event) => {
        if (event.key === 's' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            setVisible(!visible)
        }
    })

    return (
        <div className="universal-search">
            <Popup
                overlay={
                    <TaxonomicFilter
                        taxonomicFilterLogicKey="universalSearch"
                        groupType={groupType}
                        value={value}
                        taxonomicGroupTypes={groupTypes ?? [groupType]}
                    />
                }
                visible={visible}
                placement="right-start"
                fallbackPlacements={['bottom']}
                onClickOutside={() => setVisible(false)}
                modifier={{
                    name: 'offset',
                    options: {
                        // @ts-ignore
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
                            'universal-search-box',
                            isSideBarShown && 'universal-search-box--sidebar-shown'
                        )}
                        style={style}
                    >
                        <Input
                            style={{ flexGrow: 1, cursor: 'pointer', opacity: visible ? '0' : '1' }}
                            data-attr="universal-search-field"
                            placeholder={'Search ' + searchPlaceholder}
                            value={searchQuery}
                            prefix={<IconMagnifier className={clsx('magnifier-icon', 'magnifier-icon-active222')} />}
                        />
                    </div>
                )}
            </Popup>
        </div>
    )
}
