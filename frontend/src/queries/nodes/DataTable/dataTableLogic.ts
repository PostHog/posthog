import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { DataTableNode, DataTableColumn } from '~/queries/schema'
import { defaultsForDataTable } from './defaults'
import { sortedKeys } from 'lib/utils'
import { isEventsNode } from '~/queries/utils'
import { Sorting } from 'lib/components/LemonTable'

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
    defaultEventsColumns?: DataTableColumn[]
}

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => props.key),
    path(['queries', 'nodes', 'DataTable', 'dataTableLogic']),
    actions({ setColumns: (columns: DataTableColumn[]) => ({ columns }) }),
    reducers(({ props }) => ({
        columns: [
            defaultsForDataTable(props.query, props.defaultEventsColumns),
            { setColumns: (_, { columns }) => columns },
        ],
    })),
    selectors({
        queryWithDefaults: [
            (s) => [(_, props) => props.query, s.columns],
            (query: DataTableNode, columns): Required<DataTableNode> => {
                const { kind, columns: _columns, source, ...rest } = query
                return {
                    kind,
                    columns: columns,
                    source,
                    ...sortedKeys({
                        ...rest,
                        expandable:
                            isEventsNode(query.source) && query.source.select ? false : query.expandable ?? true,
                        propertiesViaUrl: query.propertiesViaUrl ?? false,
                        showPropertyFilter: query.showPropertyFilter ?? false,
                        showEventFilter: query.showEventFilter ?? false,
                        showSearch: query.showSearch ?? false,
                        showActions:
                            isEventsNode(query.source) && query.source.select ? false : query.showActions ?? true,
                        showExport: query.showExport ?? false,
                        showReload: query.showReload ?? false,
                        showColumnConfigurator: query.showColumnConfigurator ?? false,
                        showEventsBufferWarning: query.showEventsBufferWarning ?? false,
                    }),
                }
            },
        ],
        canSort: [
            (s) => [s.queryWithDefaults],
            (query: DataTableNode): boolean => isEventsNode(query.source) && !!query.source.select,
        ],
        sorting: [
            (s) => [s.queryWithDefaults, s.canSort],
            (query, canSort): Sorting | null => {
                if (canSort && isEventsNode(query.source) && query.source.orderBy && query.source.orderBy.length > 0) {
                    return query.source.orderBy[0] === '-'
                        ? {
                              columnKey: query.source.orderBy[0].substring(1),
                              order: -1,
                          }
                        : {
                              columnKey: query.source.orderBy[0],
                              order: 1,
                          }
                }
                return null
            },
        ],
    }),
    propsChanged(({ actions, props }, oldProps) => {
        const newColumns = defaultsForDataTable(props.query, props.defaultEventsColumns)
        const oldColumns = defaultsForDataTable(oldProps.query, oldProps.defaultEventsColumns)
        if (JSON.stringify(newColumns) !== JSON.stringify(oldColumns)) {
            actions.setColumns(newColumns)
        }
    }),
])
