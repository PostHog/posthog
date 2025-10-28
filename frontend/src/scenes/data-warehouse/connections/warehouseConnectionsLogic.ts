import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { WarehouseConnection, WarehouseConnectionCreatePayload } from '~/types'

import type { warehouseConnectionsLogicType } from './warehouseConnectionsLogicType'

const defaultConnectionForm: WarehouseConnectionCreatePayload = {
    name: '',
    provider: 'bigquery',
    credentials: {},
    mode: 'sync',
    config: {},
}

export const warehouseConnectionsLogic = kea<warehouseConnectionsLogicType>([
    path(['scenes', 'data-warehouse', 'connections', 'warehouseConnectionsLogic']),
    actions({
        deleteConnection: (id: string) => ({ id }),
        testConnection: (id: string) => ({ id }),
        setModalOpen: (open: boolean) => ({ open }),
        setEditingConnection: (connection: WarehouseConnection | null) => ({ connection }),
        setConnectionForm: (form: WarehouseConnectionCreatePayload) => ({ form }),
        submitConnectionForm: true,
        testConnectionForm: true,
        setConnectionTestResult: (result: { success: boolean; message: string } | null) => ({ result }),
    }),
    loaders(({ actions, values }) => ({
        connections: [
            [] as WarehouseConnection[],
            {
                loadConnections: async () => {
                    const response = await api.warehouseConnections().get()
                    return response.results || []
                },
                createConnection: async (payload: WarehouseConnectionCreatePayload) => {
                    try {
                        const newConnection = await api.warehouseConnections().create(payload)
                        lemonToast.success('Connection created successfully')
                        actions.setModalOpen(false)
                        return [newConnection, ...values.connections]
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to create connection')
                        throw error
                    }
                },
                updateConnection: async ({
                    id,
                    payload,
                }: {
                    id: string
                    payload: Partial<WarehouseConnectionCreatePayload>
                }) => {
                    try {
                        const updated = await api.warehouseConnection(id).update(payload)
                        lemonToast.success('Connection updated successfully')
                        actions.setModalOpen(false)
                        return values.connections.map((c) => (c.id === id ? updated : c))
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to update connection')
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        modalOpen: [
            false as boolean,
            {
                setModalOpen: (_, { open }) => open,
            },
        ],
        editingConnection: [
            null as WarehouseConnection | null,
            {
                setEditingConnection: (_, { connection }) => connection,
                setModalOpen: (state, { open }) => (open ? state : null),
            },
        ],
        connectionForm: [
            defaultConnectionForm,
            {
                setConnectionForm: (_, { form }) => form,
                setModalOpen: (state, { open }) => (open ? state : defaultConnectionForm),
            },
        ],
        connectionTestResult: [
            null as { success: boolean; message: string } | null,
            {
                setConnectionTestResult: (_, { result }) => result,
                setModalOpen: () => null,
                setConnectionForm: () => null,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        testResult: [
            null as { status: string; message: string } | null,
            {
                testConnectionForm: async () => {
                    actions.setConnectionTestResult(null)
                    try {
                        const result = await api.warehouseConnections().addPathComponent('test').create({
                            ...values.connectionForm,
                        })
                        const success = result.status === 'success'
                        actions.setConnectionTestResult({
                            success,
                            message: result.message || (success ? 'Connection successful!' : 'Connection failed'),
                        })
                        return result
                    } catch (error: any) {
                        const message = error.detail || error.message || 'Failed to test connection'
                        actions.setConnectionTestResult({ success: false, message })
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        hasConnections: [(s) => [s.connections], (connections) => connections.length > 0],
        healthyConnections: [
            (s) => [s.connections],
            (connections) => connections.filter((c) => c.connection_status === 'healthy'),
        ],
        isConnectionFormSubmitting: [(s) => [s.connectionsLoading], (loading) => loading],
        isTestingConnection: [(s) => [s.testResultLoading], (loading) => loading],
    }),
    listeners(({ actions, values }) => ({
        deleteConnection: async ({ id }) => {
            try {
                await api.warehouseConnection(id).delete()
                lemonToast.success('Connection deleted')
                actions.loadConnections()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to delete connection')
            }
        },
        testConnection: async ({ id }) => {
            try {
                const result = await api.warehouseConnection(id).addPathComponent('test').create()
                if (result.status === 'success') {
                    lemonToast.success('Connection test successful!')
                    actions.loadConnections()
                } else {
                    lemonToast.error(`Connection test failed: ${result.message}`)
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to test connection')
            }
        },
        submitConnectionForm: async () => {
            if (values.editingConnection) {
                await actions.updateConnection({ id: values.editingConnection.id, payload: values.connectionForm })
            } else {
                await actions.createConnection(values.connectionForm)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadConnections()
    }),
])
