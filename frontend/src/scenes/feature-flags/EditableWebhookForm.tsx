import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils'

import { WebhookSubscription } from '~/types'

// Custom hook to manage headers state and operations
interface HeaderEntry {
    id: string
    key: string
    value: string
}

function useHeadersManagement(initialHeaders: Record<string, string> = {}): {
    headers: Record<string, string>
    headerEntries: HeaderEntry[]
    addHeader: () => void
    updateHeader: (id: string, newKey: string, newValue: string) => void
    removeHeader: (id: string) => void
    resetHeaders: (newHeaders?: Record<string, string>) => void
} {
    // Convert headers to array with stable IDs
    const [headerEntries, setHeaderEntries] = useState<HeaderEntry[]>(() =>
        Object.entries(initialHeaders).map(([key, value], index) => ({
            id: `header-${index}-${Date.now()}`,
            key,
            value,
        }))
    )

    const addHeader = (): void => {
        const newEntry: HeaderEntry = {
            id: `header-${headerEntries.length}-${Date.now()}`,
            key: '',
            value: '',
        }
        setHeaderEntries([...headerEntries, newEntry])
    }

    const updateHeader = (id: string, newKey: string, newValue: string): void => {
        setHeaderEntries((entries) =>
            entries.map((entry) => (entry.id === id ? { ...entry, key: newKey, value: newValue } : entry))
        )
    }

    const removeHeader = (id: string): void => {
        setHeaderEntries((entries) => entries.filter((entry) => entry.id !== id))
    }

    const resetHeaders = (newHeaders: Record<string, string> = {}): void => {
        setHeaderEntries(
            Object.entries(newHeaders).map(([key, value], index) => ({
                id: `header-${index}-${Date.now()}`,
                key,
                value,
            }))
        )
    }

    // Convert back to headers object for external consumption
    const headers = headerEntries.reduce(
        (acc, entry) => {
            if (entry.key.trim()) {
                acc[entry.key] = entry.value
            }
            return acc
        },
        {} as Record<string, string>
    )

    return {
        headers,
        headerEntries,
        addHeader,
        updateHeader,
        removeHeader,
        resetHeaders,
    }
}

// Component for editing header entries
interface HeaderEditorProps {
    headerEntries: HeaderEntry[]
    onAddHeader: () => void
    onUpdateHeader: (id: string, newKey: string, newValue: string) => void
    onRemoveHeader: (id: string) => void
    emptyMessage?: string
}

function HeaderEditor({
    headerEntries,
    onAddHeader,
    onUpdateHeader,
    onRemoveHeader,
    emptyMessage = 'No custom headers. Click "Add Header" to add some.',
}: HeaderEditorProps): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h5 className="text-sm font-medium">Custom Headers</h5>
                <LemonButton size="small" icon={<IconPlus />} onClick={onAddHeader}>
                    Add Header
                </LemonButton>
            </div>
            {headerEntries.map((entry) => (
                <div key={entry.id} className="flex gap-2 items-center">
                    <LemonInput
                        placeholder="Header name"
                        value={entry.key}
                        onChange={(newKey) => onUpdateHeader(entry.id, newKey, entry.value)}
                        className="flex-1"
                    />
                    <LemonInput
                        placeholder="Header value"
                        value={entry.value}
                        onChange={(newValue) => onUpdateHeader(entry.id, entry.key, newValue)}
                        className="flex-1"
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => onRemoveHeader(entry.id)}
                    />
                </div>
            ))}
            {headerEntries.length === 0 && <p className="text-muted text-sm">{emptyMessage}</p>}
        </div>
    )
}

interface WebhookSubscriptionCardProps {
    subscription: WebhookSubscription
    index: number
    onUpdate: (index: number, subscription: WebhookSubscription) => void
    onRemove: (index: number) => void
}

function isValidUrl(url: string): boolean {
    try {
        const urlObj = new URL(url)
        return urlObj.protocol === 'http:' || urlObj.protocol === 'https:'
    } catch {
        return false
    }
}

function WebhookSubscriptionCard({
    subscription,
    index,
    onUpdate,
    onRemove,
}: WebhookSubscriptionCardProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [editUrl, setEditUrl] = useState(subscription.url)
    const {
        headers: editHeaders,
        headerEntries: editHeaderEntries,
        addHeader,
        updateHeader,
        removeHeader,
        resetHeaders,
    } = useHeadersManagement(subscription.headers || {})

    const handleUrlChange = (newUrl: string): void => {
        setEditUrl(newUrl)
        // If URL changed from original, clear headers since they're encrypted/redacted
        // and user needs to provide headers for the new endpoint
        if (newUrl.trim() !== subscription.url) {
            resetHeaders()
        }
    }

    const handleSave = (): void => {
        if (editUrl.trim() && isValidUrl(editUrl.trim())) {
            const updatedSubscription: WebhookSubscription = {
                url: editUrl.trim(),
                headers: Object.keys(editHeaders).length > 0 ? editHeaders : undefined,
            }
            onUpdate(index, updatedSubscription)
            setIsEditing(false)
        }
    }

    const handleCancel = (): void => {
        setEditUrl(subscription.url)
        resetHeaders(subscription.headers || {})
        setIsEditing(false)
    }

    if (isEditing) {
        return (
            <div className="p-4 border rounded bg-bg-light space-y-3">
                <div>
                    <label className="block text-sm font-medium mb-1">Webhook URL</label>
                    <LemonInput
                        value={editUrl}
                        onChange={handleUrlChange}
                        placeholder="https://example.com/webhook"
                        type="url"
                    />
                </div>

                <HeaderEditor
                    headerEntries={editHeaderEntries}
                    onAddHeader={addHeader}
                    onUpdateHeader={updateHeader}
                    onRemoveHeader={removeHeader}
                />

                <div className="flex gap-2 justify-end">
                    <LemonButton onClick={handleCancel}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabledReason={!editUrl.trim() || !isValidUrl(editUrl.trim()) ? 'Empty or invalid URL' : ''}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        )
    }

    const headersLen = Object.keys(subscription?.headers || {}).length

    return (
        <div className="p-3 border rounded bg-bg-light">
            <div className="flex items-start justify-between">
                <div className="flex-1">
                    <div className="font-mono text-sm break-all mb-2">{subscription.url}</div>
                    {subscription.headers && headersLen > 0 && (
                        <LemonCollapse
                            panels={[
                                {
                                    key: 'headers',
                                    header: pluralize(headersLen, 'custom header'),
                                    content: (
                                        <div className="space-y-1">
                                            {Object.entries(subscription.headers).map(([key, value]) => (
                                                <div key={key} className="flex gap-2 text-sm">
                                                    <span className="font-semibold text-muted flex-shrink-0">
                                                        {key}:
                                                    </span>
                                                    <span className="font-mono break-all overflow-hidden">{value}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )}
                </div>
                <div className="flex gap-2 ml-2">
                    <LemonButton size="small" onClick={() => setIsEditing(true)} tooltip="Edit webhook">
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => onRemove(index)}
                        tooltip="Remove webhook"
                    />
                </div>
            </div>
        </div>
    )
}

export function EditableWebhookForm(): JSX.Element {
    const [newUrl, setNewUrl] = useState('')
    const [showHeadersForm, setShowHeadersForm] = useState(false)
    const {
        headers: newHeaders,
        headerEntries: newHeaderEntries,
        addHeader,
        updateHeader,
        removeHeader,
        resetHeaders,
    } = useHeadersManagement()

    return (
        <div className="border rounded bg-surface-primary">
            <h3 className="p-2 mb-0">Webhook Subscriptions</h3>
            <div className="p-3 space-y-4">
                <p className="text-muted text-sm">
                    Configure webhooks that will receive notifications when this feature flag changes.
                </p>

                <LemonField name="webhook_subscriptions">
                    {({ value, onChange }) => {
                        const webhookSubscriptions = value || []

                        const handleAddSubscription = (): void => {
                            if (newUrl.trim() && isValidUrl(newUrl.trim())) {
                                const subscription: WebhookSubscription = {
                                    url: newUrl.trim(),
                                    headers: Object.keys(newHeaders).length > 0 ? newHeaders : undefined,
                                }
                                onChange([...webhookSubscriptions, subscription])
                                setNewUrl('')
                                resetHeaders()
                                setShowHeadersForm(false)
                            }
                        }

                        const handleRemoveSubscription = (index: number): void => {
                            const updated = [...webhookSubscriptions]
                            updated.splice(index, 1)
                            onChange(updated)
                        }

                        const handleUpdateSubscription = (index: number, subscription: WebhookSubscription): void => {
                            const updated = [...webhookSubscriptions]
                            updated[index] = subscription
                            onChange(updated)
                        }

                        return (
                            <div className="space-y-4">
                                {/* Add new webhook subscription */}
                                <div className="space-y-4 p-4 border rounded bg-bg-light">
                                    <div className="flex gap-2 items-end">
                                        <div className="flex-1">
                                            <label className="block text-sm font-medium mb-1">Webhook URL</label>
                                            <LemonInput
                                                value={newUrl}
                                                onChange={setNewUrl}
                                                placeholder="https://example.com/webhook"
                                                type="url"
                                            />
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => setShowHeadersForm(!showHeadersForm)}
                                        >
                                            {showHeadersForm ? 'Hide Headers' : 'Add Headers'}
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            icon={<IconPlus />}
                                            onClick={handleAddSubscription}
                                            disabledReason={
                                                !newUrl.trim() || !isValidUrl(newUrl.trim())
                                                    ? 'Empty or invalid URL'
                                                    : ''
                                            }
                                        >
                                            Save Webhook
                                        </LemonButton>
                                    </div>

                                    {showHeadersForm && (
                                        <HeaderEditor
                                            headerEntries={newHeaderEntries}
                                            onAddHeader={addHeader}
                                            onUpdateHeader={updateHeader}
                                            onRemoveHeader={removeHeader}
                                        />
                                    )}
                                </div>

                                {/* List of existing webhook subscriptions */}
                                {webhookSubscriptions.length > 0 && (
                                    <div>
                                        <h4 className="text-base font-medium mb-2">Configured Webhooks</h4>
                                        <div className="space-y-2">
                                            {webhookSubscriptions.map(
                                                (subscription: WebhookSubscription, index: number) => (
                                                    <WebhookSubscriptionCard
                                                        key={`${subscription.url}-${index}`}
                                                        subscription={subscription}
                                                        index={index}
                                                        onUpdate={handleUpdateSubscription}
                                                        onRemove={handleRemoveSubscription}
                                                    />
                                                )
                                            )}
                                        </div>
                                    </div>
                                )}

                                {webhookSubscriptions.length === 0 && (
                                    <div className="text-center py-4 text-muted">
                                        <p>No webhooks configured.</p>
                                        <p className="text-sm">Add a webhook above to start receiving notifications.</p>
                                    </div>
                                )}
                            </div>
                        )
                    }}
                </LemonField>
            </div>
        </div>
    )
}
