import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'

export interface ColumnConfiguratorLogicProps {
    key: string
    columns: string[]
    setColumns: (columns: string[]) => void
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>([
    props({} as ColumnConfiguratorLogicProps),
    path(['queries', 'nodes', 'DataTable', 'columnConfiguratorLogic']),
    key((props) => props.key),
    actions({
        showModal: true,
        hideModal: true,
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        setColumns: (columns: string[]) => ({ columns }),
        moveColumn: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        save: true,
    }),
    reducers(({ props }) => ({
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                save: () => false,
            },
        ],
        columns: [
            props.columns,
            {
                setColumns: (_, { columns }) => columns,
                selectColumn: (state, { column }) => Array.from(new Set([...state, column])),
                unselectColumn: (state, { column }) => state.filter((c) => c !== column),
                moveColumn: (state, { oldIndex, newIndex }) => {
                    const newColumns = [...state]
                    const [removed] = newColumns.splice(oldIndex, 1)
                    newColumns.splice(newIndex, 0, removed)
                    return newColumns
                },
            },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (JSON.stringify(props.columns) !== JSON.stringify(oldProps.columns)) {
            actions.setColumns(props.columns)
        }
    }),
    listeners(({ values, props }) => ({
        save: () => {
            props.setColumns(values.columns)
        },
    })),
])
