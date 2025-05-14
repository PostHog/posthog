import { LemonButton, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconCopy, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { SceneExport } from 'scenes/sceneTypes'

import { ShortLink, shortLinksLogic } from './shortLinksLogic'

export function ShortLinksScene(): JSX.Element {
    const { activeShortLinks, expiredShortLinks, newLink, shortLinksLoading, editingLink } =
        useValues(shortLinksLogic)
    const {
        setNewLinkDestinationUrl,
        setNewLinkExpirationDate,
        createShortLink,
        deleteShortLink,
        setEditingLink,
        updateShortLink,
    } = useActions(shortLinksLogic)

    const baseUrl = `${window.location.origin}/e`

    const columns = [
        {
            title: 'Short URL',
            dataIndex: 'key' as keyof ShortLink,
            render: function RenderKey(key: string | undefined) {
                if (!key) return null
                const shortUrl = `${baseUrl}/${key}`
                return (
                    <div className="flex items-center gap-2">
                        <Link to={shortUrl} target="_blank">
                            {shortUrl}
                        </Link>
                        <LemonButton
                            icon={<IconCopy />}
                            size="small"
                            onClick={() => {
                                navigator.clipboard.writeText(shortUrl)
                            }}
                            tooltip="Copy to clipboard"
                        />
                    </div>
                )
            },
        },
        {
            title: 'Destination',
            dataIndex: 'destination_url' as keyof ShortLink,
            render: function RenderDestination(destination: string | undefined) {
                if (!destination) return null
                return (
                    <Link to={destination} target="_blank" className="truncate max-w-100">
                        {destination}
                    </Link>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at' as keyof ShortLink,
            render: function RenderDate(date: string | undefined) {
                if (!date) return null
                return dayjs(date).format('MMM D, YYYY')
            },
        },
        {
            title: 'Expires',
            dataIndex: 'expiration_date' as keyof ShortLink,
            render: function RenderExpiry(date: string | undefined) {
                if (!date) {
                    return <span className="text-muted">Never</span>
                }
                return dayjs(date).format('MMM D, YYYY')
            },
        },
        {
            title: 'Actions',
            dataIndex: 'key' as keyof ShortLink,
            render: function RenderActions(key: string | undefined, record: ShortLink) {
                if (!key) return null
                return (
                    <div className="flex gap-2">
                        <LemonButton
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => setEditingLink(record)}
                            tooltip="Edit"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            size="small"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete short link?',
                                    description: (
                                        <>
                                            Are you sure you want to delete the short link{' '}
                                            <code>{baseUrl}/{key}</code>?
                                        </>
                                    ),
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Delete',
                                        onClick: () => deleteShortLink(key),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                            tooltip="Delete"
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="shortlinks-scene">
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h1 className="mb-0">Short Links</h1>
                    <p className="text-muted mb-0">Create and manage shortened URLs for easy sharing</p>
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Create Short Link',
                            width: 600,
                            content: (
                                <div className="space-y-4">
                                    <div>
                                        <LemonLabel>Destination URL</LemonLabel>
                                        <LemonInput
                                            placeholder="https://example.com"
                                            value={newLink.destination_url}
                                            onChange={(e) => setNewLinkDestinationUrl(e)}
                                            fullWidth
                                        />
                                    </div>
                                    <div>
                                        <LemonLabel>Expiration date (optional)</LemonLabel>
                                        <LemonInput
                                            type="text"
                                            placeholder="YYYY-MM-DD"
                                            value={newLink.expiration_date || ''}
                                            onChange={(e: string) =>
                                                setNewLinkExpirationDate(e ? e : null)
                                            }
                                            fullWidth
                                        />
                                    </div>
                                </div>
                            ),
                            primaryButton: {
                                children: 'Create',
                                type: 'primary',
                                onClick: () => createShortLink(),
                                disabled: !newLink.destination_url,
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    }}
                >
                    Create short link
                </LemonButton>
            </div>

            {activeShortLinks.length === 0 && !shortLinksLoading ? (
                <LemonBanner type="info">
                    No short links yet. Create your first short link to get started.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={activeShortLinks}
                    columns={columns}
                    loading={shortLinksLoading}
                    rowKey="key"
                    pagination={{ pageSize: 10 }}
                    defaultSorting={{
                        columnKey: 'created_at',
                        order: -1,
                    }}
                    nouns={['short link', 'short links']}
                />
            )}

            {expiredShortLinks.length > 0 && (
                <>
                    <div className="mt-8 mb-4">
                        <h2>Expired Links</h2>
                        <p className="text-muted mb-0">
                            These links have expired and are no longer active
                        </p>
                    </div>
                    <LemonTable
                        dataSource={expiredShortLinks}
                        columns={columns}
                        rowKey="key"
                        pagination={{ pageSize: 10 }}
                        nouns={['expired link', 'expired links']}
                    />
                </>
            )}

            {/* Edit Modal */}
            {editingLink && (
                <LemonModal
                    isOpen={!!editingLink}
                    title="Edit Short Link"
                    onClose={() => setEditingLink(null)}
                    footer={
                        <>
                            <LemonButton type="secondary" onClick={() => setEditingLink(null)}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    if (editingLink) {
                                        updateShortLink(editingLink.key, {
                                            destination_url: editingLink.destination_url,
                                            expiration_date: editingLink.expiration_date,
                                        })
                                    }
                                }}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                >
                    <div className="space-y-4">
                        <div>
                            <LemonLabel>Short URL</LemonLabel>
                            <div className="font-mono px-2 py-1 border rounded bg-bg-light">
                                {baseUrl}/{editingLink.key}
                            </div>
                        </div>
                        <div>
                            <LemonLabel>Destination URL</LemonLabel>
                            <LemonInput
                                placeholder="https://example.com"
                                value={editingLink.destination_url}
                                onChange={(e) =>
                                    setEditingLink({
                                        ...editingLink,
                                        destination_url: e,
                                    })
                                }
                                fullWidth
                            />
                        </div>
                        <div>
                            <LemonLabel>Expiration date (optional)</LemonLabel>
                            <LemonInput
                                type="text"
                                placeholder="YYYY-MM-DD"
                                value={editingLink.expiration_date || ''}
                                onChange={(e) =>
                                    setEditingLink({
                                        ...editingLink,
                                        expiration_date: e || undefined,
                                    })
                                }
                                fullWidth
                            />
                        </div>
                    </div>
                </LemonModal>
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: ShortLinksScene,
    logic: shortLinksLogic,
} 