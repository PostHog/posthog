import { kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DataModelingDAG, DataModelingSyncInterval } from '~/types'

import type { dagsLogicType } from './dagsLogicType'

export const SYNC_FREQUENCY_OPTIONS: { value: DataModelingSyncInterval; label: string }[] = [
    { value: '15min', label: '15 minutes' },
    { value: '30min', label: '30 minutes' },
    { value: '1hour', label: '1 hour' },
    { value: '6hour', label: '6 hours' },
    { value: '12hour', label: '12 hours' },
    { value: '24hour', label: 'Daily' },
    { value: '7day', label: 'Weekly' },
    { value: '30day', label: 'Monthly' },
]

export const dagsLogic = kea<dagsLogicType>([
    path(['scenes', 'models', 'dagsLogic']),
    loaders(({ values }) => ({
        dags: {
            __default: [] as DataModelingDAG[],
            loadDags: async (): Promise<DataModelingDAG[]> => {
                const response = await api.dataModelingDags.list()
                return response.results
            },
            updateDag: async (dag: DataModelingDAG): Promise<DataModelingDAG[]> => {
                const updated = await api.dataModelingDags.update(dag.id, {
                    name: dag.name,
                    description: dag.description,
                    sync_frequency: dag.sync_frequency,
                })
                return values.dags.map((d) => (d.id === updated.id ? updated : d))
            },
            deleteDag: async (dag: DataModelingDAG): Promise<DataModelingDAG[]> => {
                await api.dataModelingDags.delete(dag.id)
                return values.dags.filter((d) => d.id !== dag.id)
            },
        },
    })),
    listeners(() => ({
        updateDagSuccess: () => {
            lemonToast.success('DAG updated')
        },
        updateDagFailure: ({ error }) => {
            lemonToast.error(`Failed to update DAG: ${error?.message ?? 'Unknown error'}`)
        },
        deleteDagSuccess: () => {
            lemonToast.success('DAG deleted')
        },
        deleteDagFailure: ({ error }) => {
            lemonToast.error(`Failed to delete DAG: ${error?.message ?? 'Unknown error'}`)
        },
    })),
])
