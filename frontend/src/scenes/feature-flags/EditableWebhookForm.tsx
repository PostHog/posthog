import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonCollapse } from '@posthog/lemon-ui'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils'
import { useState } from 'react'

import { WebhookSubscription } from '~/types'

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
    const [editHeaders, setEditHeaders] = useState<Record<string, string>>(subscription.headers || {})

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
        setEditHeaders(subscription.headers || {})
        setIsEditing(false)
    }

    const addHeader = (): void => {
        setEditHeaders({ ...editHeaders, '': '' })
    }

    const updateHeader = (oldKey: string, newKey: string, value: string): void => {
        const updated = { ...editHeaders }
        delete updated[oldKey]
        if (newKey.trim()) {
            updated[newKey] = value
        }
        setEditHeaders(updated)
    }

    const removeHeader = (key: string): void => {
        const updated = { ...editHeaders }
        delete updated[key]
        setEditHeaders(updated)
    }

    if (isEditing) {
        return (
            <div className="p-4 border rounded bg-bg-light space-y-3">
                <div>
                    <label className="block text-sm font-medium mb-1">Webhook URL</label>
                    <LemonInput
                        value={editUrl}
                        onChange={setEditUrl}
                        placeholder="https://example.com/webhook"
                        type="url"
                    />
                </div>

                <div className="space-y-2">
                    <div className="flex items-center justify-between">
                        <h5 className="text-sm font-medium">Custom Headers</h5>
                        <LemonButton size="small" icon={<IconPlus />} onClick={addHeader}>
                            Add Header
                        </LemonButton>
                    </div>
                    {Object.entries(editHeaders).map(([key, value]) => (
                        <div key={key} className="flex gap-2 items-center">
                            <LemonInput
                                placeholder="Header name"
                                value={key}
                                onChange={(newKey) => updateHeader(key, newKey, value)}
                                className="flex-1"
                            />
                            <LemonInput
                                placeholder="Header value"
                                value={value}
                                onChange={(newValue) => updateHeader(key, key, newValue)}
                                className="flex-1"
                            />
                            <LemonButton
                                size="small"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => removeHeader(key)}
                            />
                        </div>
                    ))}
                    {Object.keys(editHeaders).length === 0 && (
                        <p className="text-muted text-sm">No custom headers. Click "Add Header" to add some.</p>
                    )}
                </div>

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
    const [newHeaders, setNewHeaders] = useState<Record<string, string>>({})
    const [showHeadersForm, setShowHeadersForm] = useState(false)

    const addHeader = (): void => {
        setNewHeaders({ ...newHeaders, '': '' })
    }

    const updateHeader = (oldKey: string, newKey: string, value: string): void => {
        const updated = { ...newHeaders }
        delete updated[oldKey]
        if (newKey.trim()) {
            updated[newKey] = value
        }
        setNewHeaders(updated)
    }

    const removeHeader = (key: string): void => {
        const updated = { ...newHeaders }
        delete updated[key]
        setNewHeaders(updated)
    }

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
                                setNewHeaders({})
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
                                        <div className="space-y-2">
                                            <div className="flex items-center justify-between">
                                                <h4 className="text-sm font-medium">Custom Headers</h4>
                                                <LemonButton size="small" icon={<IconPlus />} onClick={addHeader}>
                                                    Add Header
                                                </LemonButton>
                                            </div>
                                            {Object.entries(newHeaders).map(([key, value]) => (
                                                <div key={key} className="flex gap-2 items-center">
                                                    <LemonInput
                                                        placeholder="Header name"
                                                        value={key}
                                                        onChange={(newKey) => updateHeader(key, newKey, value)}
                                                        className="flex-1"
                                                    />
                                                    <LemonInput
                                                        placeholder="Header value"
                                                        value={value}
                                                        onChange={(newValue) => updateHeader(key, key, newValue)}
                                                        className="flex-1"
                                                    />
                                                    <LemonButton
                                                        size="small"
                                                        status="danger"
                                                        icon={<IconTrash />}
                                                        onClick={() => removeHeader(key)}
                                                    />
                                                </div>
                                            ))}
                                            {Object.keys(newHeaders).length === 0 && (
                                                <p className="text-muted text-sm">
                                                    No custom headers added. Click "Add Header" to add some.
                                                </p>
                                            )}
                                        </div>
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
                                                        key={subscription.url}
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
