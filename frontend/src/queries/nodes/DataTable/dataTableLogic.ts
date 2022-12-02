import { actions, kea, key, path, props, propsChanged, reducers } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { DataTableNode, DataTableStringColumn } from '~/queries/schema'
import { defaultDataTableStringColumns } from './defaults'

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
        columns: [
            (props.query.columns ?? props.defaultColumns ?? defaultDataTableStringColumns) as DataTableStringColumn[],
            { setColumns: (_, { columns }) => columns },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        const newColumns = props.query.columns ?? props.defaultColumns ?? defaultDataTableStringColumns
        const oldColumns = oldProps.query.columns ?? oldProps.defaultColumns ?? defaultDataTableStringColumns
        if (JSON.stringify(newColumns) !== JSON.stringify(oldColumns)) {
            actions.setColumns(newColumns)
        }
    }),
])
