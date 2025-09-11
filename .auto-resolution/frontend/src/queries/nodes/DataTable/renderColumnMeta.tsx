import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'

import { QueryFeature, getQueryFeatures } from '~/queries/nodes/DataTable/queryFeatures'
import { extractExpressionComment, removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import {
    DataTableNode,
    DataVisualizationNode,
    EventsQuery,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    isDataTableNode,
    isGroupsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    trimQuotes,
} from '~/queries/utils'

export interface ColumnMeta {
    title?: JSX.Element | string
    width?: string | number
    align?: 'left' | 'right' | 'center'
}

export function renderColumnMeta<T extends DataVisualizationNode | DataTableNode>(
    key: string,
    query: T,
    context?: QueryContext<T>
): ColumnMeta {
    let width: string | number | undefined
    let title: JSX.Element | string | undefined
    const queryFeatures = getQueryFeatures(query.source)
    let align: ColumnMeta['align']

    const queryContextColumnName = key.startsWith('context.columns.') ? trimQuotes(key.substring(16)) : undefined
    const queryContextColumn =
        (queryContextColumnName ? context?.columns?.[queryContextColumnName] : undefined) ?? context?.columns?.[key]

    const propertyName = key.startsWith('properties.') ? trimQuotes(key.substring(11)) : undefined

    if (queryContextColumnName && queryContextColumn && (queryContextColumn.title || queryContextColumn.renderTitle)) {
        const Component = queryContextColumn.renderTitle
        title = Component ? <Component columnName={queryContextColumnName} query={query} /> : queryContextColumn.title
    } else if (isHogQLQuery(query.source)) {
        title = key
        if (title.startsWith('`') && title.endsWith('`')) {
            title = title.substring(1, title.length - 1)
        }
        if (title.startsWith("tuple('__hx_tag', '")) {
            const tagName = title.substring(19, title.indexOf("'", 19))
            title =
                tagName === '__hx_obj' ? 'Object' : tagName === 'RecordingButton' ? 'Recording' : '<' + tagName + ' />'
        }
    } else if (propertyName && isGroupsQuery(query.source)) {
        const splitPropertyName = propertyName.split('--')
        title = splitPropertyName.length > 1 ? splitPropertyName[1].trim() : propertyName
    } else if (key === 'timestamp') {
        title = 'Time'
    } else if (key === 'created_at') {
        title = 'First seen'
    } else if (key === 'event') {
        title = 'Event'
    } else if (key === 'person') {
        title = 'Person'
    } else if (key.startsWith('properties.')) {
        title = (
            <PropertyKeyInfo
                value={trimQuotes(removeExpressionComment(key.substring(11)))}
                type={TaxonomicFilterGroupType.EventProperties}
                disableIcon
            />
        )
    } else if (key === 'person.$delete') {
        title = ''
        width = 0
    } else if (key.startsWith('person.properties.')) {
        title = (
            <PropertyKeyInfo
                value={trimQuotes(key.substring(18))}
                type={TaxonomicFilterGroupType.PersonProperties}
                disableIcon
            />
        )
    } else if (queryContextColumnName) {
        title = queryContextColumnName.replace('_', ' ')
    } else {
        title = queryFeatures.has(QueryFeature.selectAndOrderByColumns) ? extractExpressionComment(key) : key
    }

    if (queryContextColumn?.align) {
        align = queryContextColumn.align
    }

    if (queryContextColumn?.width) {
        width = queryContextColumn.width
    } else if (context?.columns?.[key]?.width) {
        width = context.columns[key].width
    }

    if (queryContextColumnName && queryContextColumn && (queryContextColumn.title || queryContextColumn.renderTitle)) {
        const Component = queryContextColumn.renderTitle
        title = Component ? <Component columnName={queryContextColumnName} query={query} /> : queryContextColumn.title
    } else if (context?.columns?.[key]?.title || context?.columns?.[key]?.renderTitle) {
        const Component = context?.columns?.[key]?.renderTitle
        title = Component ? <Component columnName={key} query={query} /> : context?.columns?.[key]?.title
    }

    if (queryFeatures.has(QueryFeature.selectAndOrderByColumns) && isMarketingAnalyticsTableQuery(query.source)) {
        const marketingQuery = query.source as MarketingAnalyticsTableQuery
        const sortKey = marketingQuery.orderBy?.[0]?.[0]
        const isSortedByKey = key === sortKey
        const order = isSortedByKey ? (marketingQuery.orderBy?.[0]?.[1] === 'DESC' ? -1 : 1) : undefined
        if (order) {
            title = (
                <>
                    {title}
                    <SortingIndicator order={order} />
                </>
            )
        }
    } else if (
        queryFeatures.has(QueryFeature.selectAndOrderByColumns) &&
        isDataTableNode(query) &&
        !query.allowSorting
    ) {
        const sortKey = queryFeatures.has(QueryFeature.selectAndOrderByColumns)
            ? (query.source as EventsQuery)?.orderBy?.[0]
            : null
        const sortOrder = key === sortKey ? 1 : `-${key}` === sortKey ? -1 : undefined
        if (sortOrder) {
            title = (
                <>
                    {title}
                    <SortingIndicator order={sortOrder} />
                </>
            )
        }
    }

    return {
        title,
        ...(typeof width !== 'undefined' ? { width } : {}),
        ...(align ? { align } : {}),
    }
}
