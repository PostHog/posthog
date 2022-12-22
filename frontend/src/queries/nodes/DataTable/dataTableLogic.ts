import { actions, connect, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { DataTableNode, HogQLExpression } from '~/queries/schema'
import { getColumnsForQuery } from './utils'
import { sortedKeys } from 'lib/utils'
import { isEventsQuery } from '~/queries/utils'
import { Sorting } from 'lib/components/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
}

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => props.key),
    path(['queries', 'nodes', 'DataTable', 'dataTableLogic']),
    actions({ setColumns: (columns: HogQLExpression[]) => ({ columns }) }),
    reducers(({ props }) => ({
        columns: [getColumnsForQuery(props.query), { setColumns: (_, { columns }) => columns }],
    })),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    selectors({
        queryWithDefaults: [
            (s) => [(_, props) => props.query, s.columns, s.featureFlags],
            (query: DataTableNode, columns, featureFlags): Required<DataTableNode> => {
                const { kind, columns: _columns, source, ...rest } = query
                const showIfFull = !!query.full
                const flagQueryRunningTimeEnabled = featureFlags[FEATURE_FLAGS.QUERY_RUNNING_TIME]
                return {
                    kind,
                    columns: columns,
                    hiddenColumns: [],
                    source,
                    ...sortedKeys({
                        ...rest,
                        full: query.full ?? false,
                        expandable: query.expandable ?? true,
                        propertiesViaUrl: query.propertiesViaUrl ?? false,
                        showPropertyFilter: query.showPropertyFilter ?? showIfFull,
                        showEventFilter: query.showEventFilter ?? showIfFull,
                        showSearch: query.showSearch ?? showIfFull,
                        showActions: query.showActions ?? true,
                        showExport: query.showExport ?? showIfFull,
                        showReload: query.showReload ?? showIfFull,
                        showElapsedTime: query.showElapsedTime ?? (flagQueryRunningTimeEnabled ? showIfFull : false),
                        showColumnConfigurator: query.showColumnConfigurator ?? showIfFull,
                        showEventsBufferWarning: query.showEventsBufferWarning ?? showIfFull,
                        allowSorting: query.allowSorting ?? true,
                    }),
                }
            },
        ],
        canSort: [
            (s) => [s.queryWithDefaults],
            (query: DataTableNode): boolean => isEventsQuery(query.source) && !!query.allowSorting,
        ],
        sorting: [
            (s) => [s.queryWithDefaults, s.canSort],
            (query, canSort): Sorting | null => {
                if (canSort && isEventsQuery(query.source) && query.source.orderBy && query.source.orderBy.length > 0) {
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
        const newColumns = getColumnsForQuery(props.query)
        const oldColumns = getColumnsForQuery(oldProps.query)
        if (JSON.stringify(newColumns) !== JSON.stringify(oldColumns)) {
            actions.setColumns(newColumns)
        }
    }),
])
