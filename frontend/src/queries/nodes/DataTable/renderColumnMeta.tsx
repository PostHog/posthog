import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { QueryContext, DataTableNode } from '~/queries/schema'
import { isEventsQuery, isHogQLQuery, trimQuotes } from '~/queries/utils'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { SortingIndicator } from 'lib/lemon-ui/LemonTable/sorting'

export interface ColumnMeta {
    title?: JSX.Element | string
    width?: number
}

export function renderColumnMeta(key: string, query: DataTableNode, context?: QueryContext): ColumnMeta {
    let width: number | undefined
    let title: JSX.Element | string | undefined

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
    } else if (key === 'url') {
        title = 'URL / Screen'
    } else if (key.startsWith('properties.')) {
        title = <PropertyKeyInfo value={trimQuotes(key.substring(11))} type={PropertyFilterType.Event} disableIcon />
    } else if (key.startsWith('context.columns.')) {
        const column = trimQuotes(key.substring(16))
        title = context?.columns?.[column]?.title ?? column.replace('_', ' ')
    } else if (key === 'person.$delete') {
        title = ''
        width = 0
    } else if (key.startsWith('person.properties.')) {
        // NOTE: PropertyFilterType.Event is not a mistake. PropertyKeyInfo only knows events vs elements ¯\_(ツ)_/¯
        title = <PropertyKeyInfo value={trimQuotes(key.substring(18))} type={PropertyFilterType.Event} disableIcon />
    } else {
        title = isEventsQuery(query.source) ? extractExpressionComment(key) : key
    }

    if (isEventsQuery(query.source) && !query.allowSorting) {
        const sortKey = isEventsQuery(query.source) ? query.source?.orderBy?.[0] : null
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
    }
}
