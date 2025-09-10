import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'
import { IconPlus, IconTrash, IconPlay, IconRefresh } from '@posthog/icons'

import { streamlitLogic } from './streamlitLogic'
import { streamlitAppsLogic } from './streamlitAppsLogic'
import { StreamlitAppViewer } from './StreamlitAppViewer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

export function StreamlitDashboard(): JSX.Element {
    const { apps, isLoading: appsLoading, runningApps, pendingApps, failedApps } = useValues(streamlitAppsLogic)
    const { createApp, deleteApp, refreshApps, openApp } = useActions(streamlitAppsLogic)
    
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
    const [newAppName, setNewAppName] = useState('')
    const [newAppDescription, setNewAppDescription] = useState('')

    const handleCreateApp = () => {
        if (newAppName.trim()) {
            createApp(newAppName.trim(), newAppDescription.trim())
            setNewAppName('')
            setNewAppDescription('')
            setIsCreateModalOpen(false)
        }
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
                    {app.description && (
                        <div className="text-sm text-muted-foreground">{app.description}</div>
                    )}
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
                <div className="text-sm text-muted-foreground">
                    {new Date(createdAt).toLocaleDateString()}
                </div>
            ),
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, app: any) => (
                <div className="flex gap-2">
                    {app.container_status === 'running' && (
                        <LemonButton
                            size="small"
                            icon={<IconPlay />}
                            onClick={() => openApp(app.id)}
                        >
                            Open
                        </LemonButton>
                    )}
                    <LemonButton
                        size="small"
                        icon={<IconTrash />}
                        status="danger"
                        onClick={() => deleteApp(app.id)}
                    >
                        Delete
                    </LemonButton>
                </div>
            ),
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
                            <p className="text-muted-foreground">
                                Deploy and manage your Streamlit applications
                            </p>
                        </div>
                        <div className="flex gap-2">
                            <LemonButton
                                icon={<IconRefresh />}
                                onClick={refreshApps}
                                loading={appsLoading}
                            >
                                Refresh
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => setIsCreateModalOpen(true)}
                            >
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
                                <LemonButton onClick={() => setIsCreateModalOpen(false)}>
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    onClick={handleCreateApp}
                                    disabled={!newAppName.trim()}
                                >
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
                        </div>
                    </LemonModal>

                    {/* Streamlit App Viewer */}
                    <StreamlitAppViewer />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
