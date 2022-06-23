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
import { PluginSelectionType, pluginsLogic } from 'scenes/plugins/pluginsLogic'
import clsx from 'clsx'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { useMountedLogic, useValues } from 'kea'
import { IconMagnifier } from '../icons'
import { useEventListener } from 'lib/hooks/useEventListener'
import { taxonomicFilterLogic } from '../TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilter } from '../TaxonomicFilter/TaxonomicFilter'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { LemonInput } from '../LemonInput/LemonInput'

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
            combineUrl(urls.projectApps(), {
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
    // Ensure some logics are mounted
    useMountedLogic(experimentsLogic)
    useMountedLogic(pluginsLogic)

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
    const { searchQuery } = useValues(logic)

    // Command+S shortcut to get to universal search popup
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
                middleware={[
                    {
                        name: 'offset',
                        fn({ x, y, placement }) {
                            if (placement === 'right-start') {
                                return { y: y - 29, x: x - 253 }
                            }
                            return {}
                        },
                    },
                ]}
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
                        {!visible && (
                            <LemonInput
                                data-attr="universal-search-field"
                                placeholder={'Search...'}
                                value={searchQuery}
                                icon={<IconMagnifier />}
                            />
                        )}
                    </div>
                )}
            </Popup>
        </div>
    )
}
