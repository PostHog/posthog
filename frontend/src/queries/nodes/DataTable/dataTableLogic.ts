import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { DataTableNode, DataTableStringColumn } from '~/queries/schema'
import { defaultDataTableColumns } from './defaults'

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
    defaultColumns?: DataTableStringColumn[]
}

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => props.key),
    path(['queries', 'nodes', 'DataTable', 'dataTableLogic']),
    actions({ setColumns: (columns: DataTableStringColumn[]) => ({ columns }) }),
    reducers(({ props }) => ({
        storedColumns: [
            (props.query.columns ??
                props.defaultColumns ??
                defaultDataTableColumns(props.query.source)) as DataTableStringColumn[],
            { setColumns: (_, { columns }) => columns },
        ],
    })),
    selectors({
        columns: [
            (s) => [s.storedColumns],
            (storedColumns) => {
                // This makes old stored columns (e.g. on the Team model) compatible with the new view that prepends 'properties.'
                const topLevelFieldsEvents = ['event', 'timestamp', 'id', 'distinct_id', 'person', 'url']
                const topLevelFieldsPersons = ['id', 'distinct_ids', 'created_at', 'is_identified', 'name', 'person']
                return storedColumns.map((column) => {
                    if (
                        topLevelFieldsEvents.includes(column) ||
                        topLevelFieldsPersons.includes(column) ||
                        column.startsWith('person.properties.') ||
                        column.startsWith('properties.') ||
                        column.startsWith('custom.')
                    ) {
                        return column
                    } else {
                        return `properties.${column}`
                    }
                })
            },
        ],
        queryWithDefaults: [
            (s) => [(_, props) => props.query, s.columns],
            (query: DataTableNode, columns): Required<DataTableNode> => ({
                ...query,
                columns: columns,
                showPropertyFilter: query.showPropertyFilter ?? false,
                showEventFilter: query.showEventFilter ?? false,
                showSearch: query.showSearch ?? false,
                showActions: query.showActions ?? true,
                showExport: query.showExport ?? false,
                showReload: query.showReload ?? false,
                showColumnConfigurator: query.showColumnConfigurator ?? false,
                showEventsBufferWarning: query.showEventsBufferWarning ?? false,
                expandable: query.expandable ?? true,
                propertiesViaUrl: query.propertiesViaUrl ?? false,
            }),
        ],
    }),
    propsChanged(({ actions, props }, oldProps) => {
        const newColumns = props.query.columns ?? props.defaultColumns ?? defaultDataTableColumns(props.query.source)
        const oldColumns =
            oldProps.query.columns ?? oldProps.defaultColumns ?? defaultDataTableColumns(oldProps.query.source)
        if (JSON.stringify(newColumns) !== JSON.stringify(oldColumns)) {
            actions.setColumns(newColumns)
        }
    }),
])
