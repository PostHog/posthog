import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { GroupTypeIndex } from '~/types'

import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'

export interface ColumnConfiguratorLogicProps {
    key: string
    columns: string[]
    setColumns: (columns: string[]) => void
    isPersistent?: boolean
    context?: {
        type: 'event_definition' | 'groups' | 'team_columns'
        eventDefinitionId?: string
        groupTypeIndex?: GroupTypeIndex
    }
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>([
    props({} as ColumnConfiguratorLogicProps),
    path(['queries', 'nodes', 'DataTable', 'columnConfiguratorLogic']),
    key((props) => props.key),
    connect(() => ({
        actions: [eventUsageLogic, ['reportDataTableColumnsUpdated'], groupsModel, ['setDefaultColumns']],
    })),
    actions({
        showModal: true,
        hideModal: true,
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        setColumns: (columns: string[]) => ({ columns }),
        moveColumn: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        save: true,
        toggleSaveAsDefault: true,
    }),
    selectors(() => ({
        context: [
            () => [(_, props) => props.context],
            (context: NonNullable<ColumnConfiguratorLogicProps['context']>) => context,
        ],
    })),
    reducers(({ props }) => ({
        saveAsDefault: [
            false,
            {
                toggleSaveAsDefault: (state) => !state,
                showModal: () => false,
            },
        ],
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
    listeners(({ actions, values, props }) => ({
        save: async () => {
            actions.reportDataTableColumnsUpdated(props.context?.type ?? 'live_events')
            if (!props.isPersistent || !values.saveAsDefault) {
                props.setColumns(values.columns)
                return
            }

            if (props.context?.type === 'groups' && typeof props.context.groupTypeIndex === 'number') {
                try {
                    actions.setDefaultColumns({
                        groupTypeIndex: props.context.groupTypeIndex,
                        defaultColumns: values.columns,
                    })
                    lemonToast.success('Default columns saved for this group type')
                } catch (error) {
                    console.error('Error saving default columns to group type:', error)
                    lemonToast.error('Failed to save columns to group type')
                }
            } else if (props.context?.type === 'event_definition' && props.context.eventDefinitionId) {
                try {
                    await api.eventDefinitions.update({
                        eventDefinitionId: props.context.eventDefinitionId,
                        eventDefinitionData: {
                            default_columns: values.columns,
                        },
                    })
                    lemonToast.success('Default columns saved for this event')
                } catch (error: any) {
                    console.error('Error saving default columns to event definition:', error)
                    lemonToast.error(error.detail || 'Failed to save columns to event definition')
                }
            } else {
                // Team-wide default columns
                teamLogic.actions.updateCurrentTeam({ live_events_columns: [HOGQL_COLUMNS_KEY, ...values.columns] })
            }

            // Always update the columns in the query
            props.setColumns(values.columns)
        },
    })),
])
