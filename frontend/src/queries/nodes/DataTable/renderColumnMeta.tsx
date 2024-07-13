import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'

import { getQueryFeatures, QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { isHogQLQuery, trimQuotes } from '~/queries/utils'

export interface ColumnMeta {
    title?: JSX.Element | string
    width?: string | number
    align?: 'left' | 'right' | 'center'
}

export function renderColumnMeta(key: string, query: DataTableNode, context?: QueryContext): ColumnMeta {
    let width: string | number | undefined
    let title: JSX.Element | string | undefined
    const queryFeatures = getQueryFeatures(query.source)
    let align: ColumnMeta['align']

    const queryContextColumnName = key.startsWith('context.columns.') ? trimQuotes(key.substring(16)) : undefined
    const queryContextColumn = queryContextColumnName ? context?.columns?.[queryContextColumnName] : undefined

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
            title = tagName === '__hx_obj' ? 'Object' : '<' + tagName + ' />'
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
        title = (
            <PropertyKeyInfo
                value={trimQuotes(key.substring(11))}
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
