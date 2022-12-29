import { PropertyFilterType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { QueryContext, DataTableNode } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'

export interface ColumnMeta {
    title?: JSX.Element | string
    width?: number
}

export function renderColumnMeta(key: string, query: DataTableNode, context?: QueryContext): ColumnMeta {
    if (key === 'timestamp') {
        return { title: 'Time' }
    } else if (key === 'created_at') {
        return { title: 'First seen' }
    } else if (key === 'event') {
        return { title: 'Event' }
    } else if (key === 'person') {
        return { title: 'Person' }
    } else if (key === 'url') {
        return { title: 'URL / Screen' }
    } else if (key.startsWith('properties.')) {
        return { title: <PropertyKeyInfo value={key.substring(11)} type={PropertyFilterType.Event} disableIcon /> }
    } else if (key.startsWith('context.columns.')) {
        return { title: context?.columns?.[key.substring(16)]?.title ?? key.substring(16).replace('_', ' ') }
    } else if (key === 'person.$delete') {
        return { title: '', width: 0 }
    } else if (key.startsWith('person.properties.')) {
        // NOTE: PropertyFilterType.Event is not a mistake. PropertyKeyInfo only knows events vs elements ¯\_(ツ)_/¯
        return { title: <PropertyKeyInfo value={key.substring(18)} type={PropertyFilterType.Event} disableIcon /> }
    } else {
        return { title: isEventsQuery(query.source) ? extractExpressionComment(key) : key }
    }
}
