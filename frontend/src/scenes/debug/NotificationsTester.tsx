import { useValues } from 'kea'
import { useState } from 'react'

import { IconBug, IconCheckCircle, IconComment, IconNotification, IconPlug, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

const NOTIFICATION_TYPES = [
    {
        type: 'comment_mention',
        label: 'Comment mention',
        icon: <IconComment className="size-5 text-primary" />,
        description: 'Someone mentioned you in a comment',
    },
    {
        type: 'alert_firing',
        label: 'Alert firing',
        icon: <IconWarning className="size-5 text-warning" />,
        description: 'An alert threshold has been breached',
    },
    {
        type: 'approval_requested',
        label: 'Approval requested',
        icon: <IconCheckCircle className="size-5 text-success" />,
        description: 'A change requires your approval',
    },
    {
        type: 'approval_resolved',
        label: 'Approval resolved',
        icon: <IconCheckCircle className="size-5 text-success" />,
        description: 'An approval request has been resolved',
    },
    {
        type: 'pipeline_failure',
        label: 'Pipeline failure',
        icon: <IconPlug className="size-5 text-danger" />,
        description: 'A data pipeline has failed',
    },
    {
        type: 'issue_assigned',
        label: 'Issue assigned',
        icon: <IconBug className="size-5 text-primary" />,
        description: 'An issue has been assigned to you',
    },
] as const

const PRIORITIES = ['normal', 'critical'] as const

export const scene: SceneExport = {
    component: NotificationsTester,
}

function NotificationsTester(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [sending, setSending] = useState<string | null>(null)
    const [lastSent, setLastSent] = useState<{ type: string; priority: string; id: string } | null>(null)

    const sendNotification = async (notificationType: string, priority: string): Promise<void> => {
        const key = `${notificationType}-${priority}`
        setSending(key)
        try {
            const response = await api.create(`api/environments/${currentTeamId}/notifications/send_test`, {
                notification_type: notificationType,
                priority,
            })
            setLastSent({ type: notificationType, priority, id: response.id })
        } catch (e) {
            console.error('Failed to send test notification', e)
        } finally {
            setSending(null)
        }
    }

    return (
        <div className="max-w-3xl mx-auto py-8 px-4">
            <div className="flex items-center gap-3 mb-2">
                <IconNotification className="size-8 text-secondary" />
                <h1 className="text-2xl font-bold mb-0">Notifications tester</h1>
            </div>
            <p className="text-secondary mb-6">
                Send test notifications to yourself to preview how each type and priority renders in the notification
                popover and as a toast.
            </p>

            <LemonBanner type="info" className="mb-6">
                Critical priority notifications will also trigger a toast popup. Make sure the livestream service is
                running with <code>LIVESTREAM_KAFKA_NOTIFICATION_ENABLED=true</code> for real-time delivery.
            </LemonBanner>

            {lastSent && (
                <LemonBanner type="success" className="mb-6" dismissKey={`notif-sent-${lastSent.id}`}>
                    Sent <strong>{lastSent.type}</strong> ({lastSent.priority}) — ID: {lastSent.id}
                </LemonBanner>
            )}

            <div className="space-y-3">
                {NOTIFICATION_TYPES.map((notif) => (
                    <div
                        key={notif.type}
                        className="flex items-center gap-4 p-4 rounded-lg border border-primary bg-surface-primary"
                    >
                        <div className="shrink-0">{notif.icon}</div>
                        <div className="flex-1 min-w-0">
                            <div className="font-semibold text-sm">{notif.label}</div>
                            <div className="text-xs text-secondary">{notif.description}</div>
                        </div>
                        <div className="flex gap-2 shrink-0">
                            {PRIORITIES.map((priority) => (
                                <LemonButton
                                    key={priority}
                                    size="small"
                                    type={priority === 'critical' ? 'primary' : 'secondary'}
                                    status={priority === 'critical' ? 'danger' : 'default'}
                                    loading={sending === `${notif.type}-${priority}`}
                                    onClick={() => sendNotification(notif.type, priority)}
                                >
                                    {priority === 'critical' ? 'Critical' : 'Normal'}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            <LemonDivider className="my-6" />

            <h2 className="text-lg font-semibold mb-3">Bulk send</h2>
            <p className="text-secondary text-sm mb-4">Send all notification types at once with a given priority.</p>
            <div className="flex gap-3">
                {PRIORITIES.map((priority) => (
                    <LemonButton
                        key={`bulk-${priority}`}
                        type={priority === 'critical' ? 'primary' : 'secondary'}
                        status={priority === 'critical' ? 'danger' : 'default'}
                        loading={sending === `bulk-${priority}`}
                        onClick={async () => {
                            setSending(`bulk-${priority}`)
                            for (const notif of NOTIFICATION_TYPES) {
                                await sendNotification(notif.type, priority)
                                await new Promise((r) => setTimeout(r, 300))
                            }
                            setSending(null)
                        }}
                    >
                        Send all ({priority})
                    </LemonButton>
                ))}

                <LemonTag type="highlight" className="self-center">
                    {NOTIFICATION_TYPES.length} types × {PRIORITIES.length} priorities
                </LemonTag>
            </div>
        </div>
    )
}

export default NotificationsTester
