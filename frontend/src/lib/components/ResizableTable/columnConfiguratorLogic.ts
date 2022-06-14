import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { kea } from 'kea'
import { ColumnChoice } from '~/types'
import { teamLogic } from 'scenes/teamLogic'

export interface ColumnConfiguratorLogicProps {
    selectedColumns: string[] // the columns the table is currently displaying
    onSaveAsDefault?: (columns: ColumnChoice) => void
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>({
    path: ['lib', 'components', 'ResizableTable', 'columnConfiguratorLogic'],
    props: { selectedColumns: [] } as ColumnConfiguratorLogicProps,
    connect: [tableConfigLogic],
    actions: {
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        resetColumns: (columns: string[]) => ({ columns }),
        setColumns: (columns: string[]) => ({ columns }),
        toggleSaveAsDefault: true,
        save: true,
    },
    reducers: ({ props }) => ({
        selectedColumns: [
            props.selectedColumns,
            {
                selectColumn: (state, { column }) => Array.from(new Set([...state, column])),
                unselectColumn: (state, { column }) => state.filter((c) => c !== column),
                resetColumns: (_, { columns }) => columns,
                setColumns: (_, { columns }) => columns,
            },
        ],
        saveAsDefault: [
            false,
            {
                toggleSaveAsDefault: (state) => !state,
                save: () => false,
            },
        ],
    }),
    listeners: ({ values, props }) => ({
        save: () => {
            tableConfigLogic.actions.setSelectedColumns(values.selectedColumns)
            if (values.saveAsDefault && props.onSaveAsDefault) {
                teamLogic.actions.updateCurrentTeam({ live_events_columns: values.selectedColumns })
            }
        },
    }),
})
