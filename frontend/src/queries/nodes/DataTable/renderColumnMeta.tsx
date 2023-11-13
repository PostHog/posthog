import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { DataTableNode, EventsQuery } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { isHogQLQuery, trimQuotes } from '~/queries/utils'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'
import { getQueryFeatures, QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'

export interface ColumnMeta {
    title?: JSX.Element | string
    width?: number
    align?: 'left' | 'right' | 'center'
}

export function renderColumnMeta(key: string, query: DataTableNode, context?: QueryContext): ColumnMeta {
    let width: number | undefined
    let title: JSX.Element | string | undefined
    const queryFeatures = getQueryFeatures(query.source)
    let align: ColumnMeta['align']

    if (isHogQLQuery(query.source)) {
        title = key
        if (title.startsWith('`') && title.endsWith('`')) {
            title = title.substring(1, title.length - 1)
        }
    } else if (key === 'timestamp') {
        title = 'Time'
    } else if (key === 'created_at') {
        title = 'First seen'
    } else if (key === 'event') {
        title = 'Event'
    } else if (key === 'person') {
        title = 'Person'
    } else if (key.startsWith('properties.')) {
        // NOTE: Sometimes these are event, sometimes person properties. We use PropertyFilterType.Event for both.
        title = <PropertyKeyInfo value={trimQuotes(key.substring(11))} type={PropertyFilterType.Event} disableIcon />
    } else if (key.startsWith('context.columns.')) {
        const column = trimQuotes(key.substring(16))
        const queryContextColumn = context?.columns?.[column]
        const Component = queryContextColumn?.renderTitle
        title = Component ? (
            <Component columnName={column} query={query} />
        ) : (
            queryContextColumn?.title ?? column.replace('_', ' ')
        )
        align = queryContextColumn?.align
    } else if (key === 'person.$delete') {
        title = ''
        width = 0
    } else if (key.startsWith('person.properties.')) {
        // NOTE: PropertyFilterType.Event is not a mistake. PropertyKeyInfo only knows events vs elements ¯\_(ツ)_/¯
        title = <PropertyKeyInfo value={trimQuotes(key.substring(18))} type={PropertyFilterType.Event} disableIcon />
    } else {
        title = queryFeatures.has(QueryFeature.selectAndOrderByColumns) ? extractExpressionComment(key) : key
    }

    if (queryFeatures.has(QueryFeature.selectAndOrderByColumns) && !query.allowSorting) {
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
