import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { WarehouseConnectionCreatePayload, WarehouseConnectionMode, WarehouseConnectionProvider } from '~/types'

import { warehouseConnectionsLogic } from './warehouseConnectionsLogic'

export function WarehouseConnectionModal(): JSX.Element {
    const { modalOpen, connectionForm, isConnectionFormSubmitting, connectionTestResult, isTestingConnection } =
        useValues(warehouseConnectionsLogic)
    const { setModalOpen, setConnectionForm, submitConnectionForm, testConnectionForm } =
        useActions(warehouseConnectionsLogic)

    const providerOptions: { value: WarehouseConnectionProvider; label: string }[] = [
        { value: 'bigquery', label: 'Google BigQuery' },
        { value: 'snowflake', label: 'Snowflake' },
        { value: 'redshift', label: 'Amazon Redshift' },
        { value: 'databricks', label: 'Databricks' },
    ]

    const modeOptions: { value: WarehouseConnectionMode; label: string; description?: string }[] = [
        {
            value: 'sync',
            label: 'Sync',
            description: 'Import data to PostHog for best query performance',
        },
        {
            value: 'direct',
            label: 'Direct',
            description: 'Query warehouse directly without importing',
        },
        {
            value: 'hybrid',
            label: 'Hybrid',
            description: 'Sync metadata, query data directly',
        },
    ]

    const renderCredentialFields = (): JSX.Element => {
        const provider = connectionForm.provider

        switch (provider) {
            case 'bigquery':
                return (
                    <div className="space-y-2">
                        <label className="block">
                            <span className="block mb-1 font-medium">Service Account JSON</span>
                            <LemonTextArea
                                value={connectionForm.credentials?.service_account_json || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { service_account_json: value },
                                    })
                                }
                                placeholder='{"type": "service_account", "project_id": "...", ...}'
                                minRows={6}
                                className="font-mono text-xs"
                            />
                            <span className="text-xs text-muted">
                                Paste the entire JSON key file for your BigQuery service account
                            </span>
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Project ID (optional)</span>
                            <LemonInput
                                value={connectionForm.config?.project_id || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        config: { ...connectionForm.config, project_id: value },
                                    })
                                }
                                placeholder="my-project-id"
                            />
                            <span className="text-xs text-muted">
                                Leave blank to use the project from service account
                            </span>
                        </label>
                    </div>
                )

            case 'snowflake':
                return (
                    <div className="space-y-2">
                        <label className="block">
                            <span className="block mb-1 font-medium">Account</span>
                            <LemonInput
                                value={connectionForm.credentials?.account || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, account: value },
                                    })
                                }
                                placeholder="abc12345.us-east-1"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Username</span>
                            <LemonInput
                                value={connectionForm.credentials?.username || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, username: value },
                                    })
                                }
                                placeholder="username"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Password</span>
                            <LemonInput
                                type="password"
                                value={connectionForm.credentials?.password || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, password: value },
                                    })
                                }
                                placeholder="••••••••"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Warehouse (optional)</span>
                            <LemonInput
                                value={connectionForm.config?.warehouse || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        config: { ...connectionForm.config, warehouse: value },
                                    })
                                }
                                placeholder="COMPUTE_WH"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Database (optional)</span>
                            <LemonInput
                                value={connectionForm.config?.database || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        config: { ...connectionForm.config, database: value },
                                    })
                                }
                                placeholder="PRODUCTION"
                            />
                        </label>
                    </div>
                )

            case 'redshift':
                return (
                    <div className="space-y-2">
                        <label className="block">
                            <span className="block mb-1 font-medium">Host</span>
                            <LemonInput
                                value={connectionForm.credentials?.host || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, host: value },
                                    })
                                }
                                placeholder="my-cluster.abc123.us-east-1.redshift.amazonaws.com"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Port</span>
                            <LemonInput
                                type="number"
                                value={connectionForm.credentials?.port || '5439'}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, port: value },
                                    })
                                }
                                placeholder="5439"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Database</span>
                            <LemonInput
                                value={connectionForm.credentials?.database || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, database: value },
                                    })
                                }
                                placeholder="analytics"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Username</span>
                            <LemonInput
                                value={connectionForm.credentials?.username || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, username: value },
                                    })
                                }
                                placeholder="username"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Password</span>
                            <LemonInput
                                type="password"
                                value={connectionForm.credentials?.password || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, password: value },
                                    })
                                }
                                placeholder="••••••••"
                            />
                        </label>
                    </div>
                )

            case 'databricks':
                return (
                    <div className="space-y-2">
                        <label className="block">
                            <span className="block mb-1 font-medium">Server Hostname</span>
                            <LemonInput
                                value={connectionForm.credentials?.server_hostname || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, server_hostname: value },
                                    })
                                }
                                placeholder="dbc-abc12345-wxyz.cloud.databricks.com"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">HTTP Path</span>
                            <LemonInput
                                value={connectionForm.credentials?.http_path || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, http_path: value },
                                    })
                                }
                                placeholder="/sql/1.0/warehouses/abc123"
                            />
                        </label>
                        <label className="block">
                            <span className="block mb-1 font-medium">Access Token</span>
                            <LemonInput
                                type="password"
                                value={connectionForm.credentials?.access_token || ''}
                                onChange={(value) =>
                                    setConnectionForm({
                                        ...connectionForm,
                                        credentials: { ...connectionForm.credentials, access_token: value },
                                    })
                                }
                                placeholder="dapi..."
                            />
                        </label>
                    </div>
                )

            default:
                return <div className="text-muted">Select a provider to configure credentials</div>
        }
    }

    return (
        <LemonModal
            isOpen={modalOpen}
            onClose={() => setModalOpen(false)}
            title="Add warehouse connection"
            width={600}
            footer={
                <div className="flex justify-between w-full">
                    <div>
                        {connectionTestResult && (
                            <span
                                className={`text-sm ${
                                    connectionTestResult.success ? 'text-success' : 'text-danger'
                                }`}
                            >
                                {connectionTestResult.message}
                            </span>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={testConnectionForm}
                            loading={isTestingConnection}
                            disabled={
                                !connectionForm.name ||
                                !connectionForm.provider ||
                                !connectionForm.credentials ||
                                Object.keys(connectionForm.credentials).length === 0
                            }
                        >
                            Test connection
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitConnectionForm}
                            loading={isConnectionFormSubmitting}
                            disabled={
                                !connectionForm.name ||
                                !connectionForm.provider ||
                                !connectionForm.credentials ||
                                Object.keys(connectionForm.credentials).length === 0
                            }
                        >
                            Create connection
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-4">
                <label className="block">
                    <span className="block mb-1 font-medium">Connection name</span>
                    <LemonInput
                        value={connectionForm.name}
                        onChange={(value) => setConnectionForm({ ...connectionForm, name: value })}
                        placeholder="Production BigQuery"
                    />
                </label>

                <label className="block">
                    <span className="block mb-1 font-medium">Provider</span>
                    <LemonSelect
                        value={connectionForm.provider}
                        onChange={(value) =>
                            setConnectionForm({
                                ...connectionForm,
                                provider: value as WarehouseConnectionProvider,
                                credentials: {},
                                config: {},
                            })
                        }
                        options={providerOptions}
                        placeholder="Select a provider"
                    />
                </label>

                <label className="block">
                    <span className="block mb-1 font-medium">Mode</span>
                    <LemonSelect
                        value={connectionForm.mode}
                        onChange={(value) =>
                            setConnectionForm({ ...connectionForm, mode: value as WarehouseConnectionMode })
                        }
                        options={modeOptions.map((opt) => ({
                            value: opt.value,
                            label: (
                                <div>
                                    <div>{opt.label}</div>
                                    {opt.description && <div className="text-xs text-muted">{opt.description}</div>}
                                </div>
                            ),
                        }))}
                    />
                </label>

                {connectionForm.provider && (
                    <div className="border-t pt-4">
                        <h3 className="mb-3 font-medium">Credentials</h3>
                        {renderCredentialFields()}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
