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

    if (isHogQLQuery(query.source)) {
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
    } else {
        const extractedKey = extractExpressionComment(key)
        if (extractedKey.startsWith('context.columns.')) {
            const column = trimQuotes(extractedKey.substring(16)) // 16 = "context.columns.".length
            const queryContextColumn = context?.columns?.[column]
            const Component = queryContextColumn?.renderTitle
            title = Component ? (
                <Component columnName={column} query={query} />
            ) : (
                queryContextColumn?.title ?? column.replace('_', ' ')
            )
            align = queryContextColumn?.align
            width = queryContextColumn?.width
        } else {
            title = queryFeatures.has(QueryFeature.selectAndOrderByColumns) ? extractExpressionComment(key) : key
        }
    }

    const specifiedWidth = context?.columns?.[key]?.width

    if (specifiedWidth) {
        width = specifiedWidth
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
