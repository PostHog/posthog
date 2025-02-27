import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/defaultEventsQuery'

import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'

export interface ColumnConfiguratorLogicProps {
    key: string
    columns: string[]
    setColumns: (columns: string[]) => void
    isPersistent?: boolean
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
        toggleSaveAsDefault: true,
    }),
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
    listeners(({ values, props }) => ({
        save: async () => {
            // Check if we're in an event definition view
            const isEventDefinition = router.values.currentLocation?.pathname.includes('/data-management/events/')

            // Regular team-wide default columns behavior - only if we're not in event definition view
            if (props.isPersistent && values.saveAsDefault && !isEventDefinition) {
                teamLogic.actions.updateCurrentTeam({ live_events_columns: [HOGQL_COLUMNS_KEY, ...values.columns] })
            }

            // Handle event definition saving
            if (props.isPersistent && isEventDefinition && values.saveAsDefault) {
                const pathname = router.values.currentLocation?.pathname || ''
                const eventDefinitionId = pathname.split('/').pop() || ''

                if (eventDefinitionId) {
                    try {
                        await api.eventDefinitions.update({
                            eventDefinitionId,
                            eventDefinitionData: {
                                default_columns: values.columns,
                            },
                        })

                        lemonToast.success('Default columns saved for this event')
                    } catch (error) {
                        console.error('Error saving default columns to event definition:', error)
                        lemonToast.error('Failed to save columns to event definition')
                    }
                }
            }

            // Always update the columns in the query
            props.setColumns(values.columns)
        },
    })),
])
