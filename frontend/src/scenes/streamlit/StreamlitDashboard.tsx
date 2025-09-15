import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlay, IconPlus, IconRefresh, IconTrash, IconServer, IconHeart, IconBug } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { StreamlitAppViewer } from './StreamlitAppViewer'
import { streamlitAppsLogic, StreamlitApp } from './streamlitAppsLogic'
import { streamlitLogic } from './streamlitLogic'

export function StreamlitDashboard(): JSX.Element {
    const { apps, isLoading: appsLoading, runningApps, pendingApps, failedApps, appHealth, appLogs } = useValues(streamlitAppsLogic)
    const { createApp, deleteApp, refreshApps, openApp, restartApp, checkAppHealth, getAppLogs } = useActions(streamlitAppsLogic)

    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
    const [newAppName, setNewAppName] = useState('')
    const [newAppDescription, setNewAppDescription] = useState('')
    const [appType, setAppType] = useState<'default' | 'custom'>('default')
    const [entrypointFile, setEntrypointFile] = useState<File | null>(null)
    const [requirementsFile, setRequirementsFile] = useState<File | null>(null)
    const [selectedAppForHealth, setSelectedAppForHealth] = useState<StreamlitApp | null>(null)
    const [selectedAppForLogs, setSelectedAppForLogs] = useState<StreamlitApp | null>(null)

    const handleCreateApp = () => {
        if (newAppName.trim()) {
            createApp(
                newAppName.trim(),
                newAppDescription.trim(),
                appType,
                entrypointFile || undefined,
                requirementsFile || undefined
            )
            setNewAppName('')
            setNewAppDescription('')
            setAppType('default')
            setEntrypointFile(null)
            setRequirementsFile(null)
            setIsCreateModalOpen(false)
        }
    }

    const handleRestartApp = (appId: string) => {
        restartApp(appId)
    }

    const handleCheckHealth = (app: StreamlitApp) => {
        setSelectedAppForHealth(app)
        checkAppHealth(app.id)
    }

    const handleGetLogs = (app: StreamlitApp) => {
        setSelectedAppForLogs(app)
        getAppLogs(app.id)
    }

    const getStatusTag = (status: string) => {
        switch (status) {
            case 'running':
                return <LemonTag type="success">Running</LemonTag>
            case 'pending':
                return <LemonTag type="warning">Pending</LemonTag>
            case 'failed':
                return <LemonTag type="danger">Failed</LemonTag>
            case 'stopped':
                return <LemonTag type="default">Stopped</LemonTag>
            default:
                return <LemonTag type="default">{status}</LemonTag>
        }
    }

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (name: string, app: any) => (
                <div>
                    <div className="font-medium">{name}</div>
                    {app.description && <div className="text-sm text-muted-foreground">{app.description}</div>}
                </div>
            ),
        },
        {
            title: 'Status',
            dataIndex: 'container_status',
            key: 'status',
            render: (status: string) => getStatusTag(status),
        },
        {
            title: 'Created By',
            dataIndex: 'created_by',
            key: 'created_by',
            render: (createdBy: any) => (
                <div className="text-sm">
                    {createdBy.first_name} {createdBy.last_name}
                </div>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (createdAt: string) => (
                <div className="text-sm text-muted-foreground">{new Date(createdAt).toLocaleDateString()}</div>
            ),
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, app: any) => {
                const canOpen = app.container_status === 'running' && app.public_url;
                
                return (
                    <div className="flex gap-2">
                        <LemonButton 
                            size="small" 
                            icon={<IconPlay />} 
                            onClick={() => openApp(app.id)}
                            disabled={!canOpen}
                            tooltip={canOpen ? "Open app" : "App not available - container not running or no URL"}
                        >
                            Open
                        </LemonButton>
                        <LemonButton 
                            size="small" 
                            icon={<IconServer />} 
                            onClick={() => handleRestartApp(app.id)}
                            tooltip="Restart container (will recreate if missing)"
                        >
                            Restart
                        </LemonButton>
                        <LemonButton 
                            size="small" 
                            icon={<IconHeart />} 
                            onClick={() => handleCheckHealth(app)}
                            tooltip="Check health"
                        >
                            Health
                        </LemonButton>
                        <LemonButton 
                            size="small" 
                            icon={<IconBug />} 
                            onClick={() => handleGetLogs(app)}
                            tooltip="View logs"
                        >
                            Logs
                        </LemonButton>
                        <LemonButton 
                            size="small" 
                            icon={<IconTrash />} 
                            status="danger" 
                            onClick={() => deleteApp(app.id)}
                            tooltip="Delete app"
                        >
                            Delete
                        </LemonButton>
                    </div>
                );
            },
        },
    ]

    return (
        <BindLogic logic={streamlitLogic} props={{}}>
            <BindLogic logic={streamlitAppsLogic} props={{}}>
                <div className="space-y-6">
                    {/* Header */}
                    <div className="flex justify-between items-center">
                        <div>
                            <h2 className="text-2xl font-bold">Streamlit Apps</h2>
                            <p className="text-muted-foreground">Deploy and manage your Streamlit applications</p>
                        </div>
                        <div className="flex gap-2">
                            <LemonButton icon={<IconRefresh />} onClick={refreshApps} loading={appsLoading}>
                                Refresh
                            </LemonButton>
                            <LemonButton type="primary" icon={<IconPlus />} onClick={() => setIsCreateModalOpen(true)}>
                                Create App
                            </LemonButton>
                        </div>
                    </div>

                    {/* Stats */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="bg-card p-4 rounded-lg border">
                            <div className="text-2xl font-bold text-green-600">{runningApps.length}</div>
                            <div className="text-sm text-muted-foreground">Running Apps</div>
                        </div>
                        <div className="bg-card p-4 rounded-lg border">
                            <div className="text-2xl font-bold text-yellow-600">{pendingApps.length}</div>
                            <div className="text-sm text-muted-foreground">Pending Apps</div>
                        </div>
                        <div className="bg-card p-4 rounded-lg border">
                            <div className="text-2xl font-bold text-red-600">{failedApps.length}</div>
                            <div className="text-sm text-muted-foreground">Failed Apps</div>
                        </div>
                    </div>

                    {/* Apps Table */}
                    <div className="bg-card rounded-lg border">
                        <LemonTable
                            dataSource={apps}
                            columns={columns}
                            loading={appsLoading}
                            emptyState={
                                <div className="text-center py-8">
                                    <h3 className="text-lg font-semibold mb-2">No Streamlit apps yet</h3>
                                    <p className="text-muted-foreground mb-4">
                                        Create your first Streamlit app to get started
                                    </p>
                                    <LemonButton
                                        type="primary"
                                        icon={<IconPlus />}
                                        onClick={() => setIsCreateModalOpen(true)}
                                    >
                                        Create App
                                    </LemonButton>
                                </div>
                            }
                        />
                    </div>

                    {/* Create App Modal */}
                    <LemonModal
                        isOpen={isCreateModalOpen}
                        onClose={() => setIsCreateModalOpen(false)}
                        title="Create Streamlit App"
                        footer={
                            <div className="flex gap-2">
                                <LemonButton onClick={() => setIsCreateModalOpen(false)}>Cancel</LemonButton>
                                <LemonButton type="primary" onClick={handleCreateApp} disabled={!newAppName.trim()}>
                                    Create App
                                </LemonButton>
                            </div>
                        }
                    >
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium mb-2">App Name</label>
                                <LemonInput
                                    value={newAppName}
                                    onChange={setNewAppName}
                                    placeholder="My Streamlit App"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium mb-2">Description (Optional)</label>
                                <LemonTextArea
                                    value={newAppDescription}
                                    onChange={setNewAppDescription}
                                    placeholder="A brief description of your app"
                                    rows={3}
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium mb-2">App Type</label>
                                <LemonSelect
                                    value={appType}
                                    onChange={setAppType}
                                    options={[
                                        { label: 'Default Hello World', value: 'default' },
                                        { label: 'Custom Uploaded App', value: 'custom' },
                                    ]}
                                    fullWidth
                                />
                            </div>

                            {appType === 'custom' && (
                                <>
                                    <div>
                                        <label className="block text-sm font-medium mb-2">
                                            Entrypoint File (Python)
                                        </label>
                                        <input
                                            type="file"
                                            accept=".py"
                                            onChange={(e) => setEntrypointFile(e.target.files?.[0] || null)}
                                            className="w-full p-2 border rounded"
                                        />
                                        <p className="text-xs text-muted-foreground mt-1">
                                            Main Python file for your Streamlit app
                                        </p>
                                    </div>

                                    <div>
                                        <label className="block text-sm font-medium mb-2">
                                            Requirements File (Optional)
                                        </label>
                                        <input
                                            type="file"
                                            accept=".txt"
                                            onChange={(e) => setRequirementsFile(e.target.files?.[0] || null)}
                                            className="w-full p-2 border rounded"
                                        />
                                        <p className="text-xs text-muted-foreground mt-1">
                                            requirements.txt file for Python dependencies
                                        </p>
                                    </div>
                                </>
                            )}
                        </div>
                    </LemonModal>

                    {/* Streamlit App Viewer */}
                    <StreamlitAppViewer />

                    {/* Health Check Modal */}
                    <LemonModal
                        isOpen={!!selectedAppForHealth}
                        onClose={() => setSelectedAppForHealth(null)}
                        title={`Health Check - ${selectedAppForHealth?.name}`}
                        footer={
                            <div className="flex justify-end">
                                <LemonButton onClick={() => setSelectedAppForHealth(null)}>Close</LemonButton>
                            </div>
                        }
                    >
                        {selectedAppForHealth && (
                            <div className="space-y-4">
                                <div className="p-4 bg-gray-50 rounded-lg">
                                    <h3 className="font-semibold mb-2">Health Status</h3>
                                    {appHealth ? (
                                        <div className="space-y-2">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium">Status:</span>
                                                <LemonTag type={appHealth.healthy ? 'success' : 'danger'}>
                                                    {appHealth.healthy ? 'Healthy' : 'Unhealthy'}
                                                </LemonTag>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium">Container Status:</span>
                                                <span className="text-sm">{appHealth.status}</span>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium">Message:</span>
                                                <span className="text-sm">{appHealth.message}</span>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="text-sm text-gray-500">Loading health check...</div>
                                    )}
                                </div>
                            </div>
                        )}
                    </LemonModal>

                    {/* Logs Modal */}
                    <LemonModal
                        isOpen={!!selectedAppForLogs}
                        onClose={() => setSelectedAppForLogs(null)}
                        title={`Container Logs - ${selectedAppForLogs?.name}`}
                        width="80%"
                        footer={
                            <div className="flex justify-end">
                                <LemonButton onClick={() => setSelectedAppForLogs(null)}>Close</LemonButton>
                            </div>
                        }
                    >
                        {selectedAppForLogs && (
                            <div className="space-y-4">
                                <div className="p-4 bg-gray-900 text-green-400 rounded-lg font-mono text-sm max-h-96 overflow-auto">
                                    {appLogs ? (
                                        <pre className="whitespace-pre-wrap">{appLogs.logs}</pre>
                                    ) : (
                                        <div className="text-gray-500">Loading logs...</div>
                                    )}
                                </div>
                            </div>
                        )}
                    </LemonModal>
                </div>
            </BindLogic>
        </BindLogic>
    )
}
