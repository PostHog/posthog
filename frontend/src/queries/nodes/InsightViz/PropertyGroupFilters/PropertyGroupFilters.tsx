import './PropertyGroupFilters.scss'

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { inlineEquivalentPropertyGroups, isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'
import {
    PropertyFilterRow,
    FilterLogicalOperator,
    InsightLogicProps,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

import { LemonPropertyGroupFilters } from './LemonPropertyGroupFilters'
import { PropertyGroupFilterLogicProps, propertyGroupFilterLogic } from './propertyGroupFilterLogic'
import { QuillPropertyGroupFilters } from './QuillPropertyGroupFilters'

export interface PropertyGroupFiltersBodyProps {
    logicProps: PropertyGroupFilterLogicProps
    insightProps: InsightLogicProps
    query: ProductAnalyticsInsightQueryNode
    setQuery: (node: ProductAnalyticsInsightQueryNode) => void
    pageKey: string
    eventNames: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    propertyGroupFilter: PropertyGroupFilter
    groupRows: (PropertyFilterRow[] | null)[]
    showHeader: boolean
    disabledReason?: string
    behavioralFiltersEnabled: boolean
    addFilterGroup: () => void
    removeFilterGroup: (filterGroup: number) => void
    duplicateFilterGroup: (propertyGroupIndex: number) => void
    setOuterPropertyGroupsType: (type: FilterLogicalOperator) => void
    setInnerPropertyGroupType: (type: FilterLogicalOperator, index: number) => void
    setPropertyFilters: (properties: any, index: number) => void
}

type PropertyGroupFiltersProps = {
    insightProps: InsightLogicProps
    query: ProductAnalyticsInsightQueryNode
    setQuery: (node: ProductAnalyticsInsightQueryNode) => void
    pageKey: string
    eventNames?: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    globalFiltersUnsupported?: boolean
}

export function PropertyGroupFilters({
    insightProps,
    query,
    setQuery,
    pageKey,
    eventNames = [],
    taxonomicGroupTypes,
    globalFiltersUnsupported,
}: PropertyGroupFiltersProps): JSX.Element {
    const logicProps = { query, setQuery, pageKey }
    const { featureFlags } = useValues(featureFlagLogic)
    const { propertyGroupFilter } = useValues(propertyGroupFilterLogic(logicProps))
    const {
        addFilterGroup,
        removeFilterGroup,
        duplicateFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
    } = useActions(propertyGroupFilterLogic(logicProps))

    const behavioralFiltersEnabled = !!featureFlags[FEATURE_FLAGS.BEHAVIORAL_PROPERTY_FILTER]
    const quillEnabled = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
    const groupRows = useMemo(
        () =>
            propertyGroupFilter.values?.map((group: PropertyGroupFilterValue) =>
                isPropertyGroupFilterLike(group) ? inlineEquivalentPropertyGroups(group.values, group.type) : null
            ) ?? [],
        [propertyGroupFilter.values]
    )
    const showHeader = propertyGroupFilter.type && propertyGroupFilter.values.length > 1
    const disabledReason = globalFiltersUnsupported
        ? 'Filter groups cannot be added to insights with a data warehouse series. Please use individual series filters instead.'
        : undefined
    const bodyProps: PropertyGroupFiltersBodyProps = {
        logicProps,
        insightProps,
        query,
        setQuery,
        pageKey,
        eventNames,
        taxonomicGroupTypes,
        propertyGroupFilter,
        groupRows,
        showHeader: !!showHeader,
        disabledReason,
        behavioralFiltersEnabled,
        addFilterGroup,
        removeFilterGroup,
        duplicateFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
    }
    return quillEnabled ? <QuillPropertyGroupFilters {...bodyProps} /> : <LemonPropertyGroupFilters {...bodyProps} />
}
