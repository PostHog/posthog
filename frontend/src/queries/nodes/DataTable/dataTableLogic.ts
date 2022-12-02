import { actions, kea, key, path, props, reducers } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { DataTableNode, DataTableStringColumn } from '~/queries/schema'
import { defaultDataTableStringColumns } from './defaults'

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
}

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => props.key),
    path(['queries', 'nodes', 'DataTable', 'dataTableLogic']),
    actions({ setColumns: (columns: DataTableStringColumn[]) => ({ columns }) }),
    reducers(({ props }) => ({
        columns: [
            (props.query.columns || defaultDataTableStringColumns) as DataTableStringColumn[],
            { setColumns: (_, { columns }) => columns },
        ],
    })),
])
