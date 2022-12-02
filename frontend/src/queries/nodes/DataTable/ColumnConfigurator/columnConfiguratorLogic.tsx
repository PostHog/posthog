import { actions, kea, listeners, path, props, propsChanged, reducers } from 'kea'
import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'
import { teamLogic } from 'scenes/teamLogic'

export interface ColumnConfiguratorLogicProps {
    key: string
    columns: string[]
    setColumns: (columns: string[]) => void
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>([
    props({} as ColumnConfiguratorLogicProps),
    path(['queries', 'nodes', 'DataTable', 'columnConfiguratorLogic']),
    actions({
        showModal: true,
        hideModal: true,
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        resetColumns: (columns: string[]) => ({ columns }),
        setColumns: (columns: string[]) => ({ columns }),
        toggleSaveAsDefault: true,
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
                resetColumns: (_, { columns }) => columns,
            },
        ],
        saveAsDefault: [
            false,
            {
                toggleSaveAsDefault: (state) => !state,
            },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (JSON.stringify(props.columns) !== JSON.stringify(oldProps.columns)) {
            actions.setColumns(props.columns)
        }
    }),
    listeners(({ values, actions, props }) => ({
        save: () => {
            props.setColumns(values.columns)
            if (values.saveAsDefault) {
                teamLogic.findMounted()?.actions.updateCurrentTeam({ live_events_columns: values.columns })
                actions.toggleSaveAsDefault()
            }
        },
    })),
])
