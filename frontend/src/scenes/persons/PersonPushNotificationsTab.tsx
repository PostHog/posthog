import { useValues } from 'kea'
import { useState } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { LemonTable, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { EmailViewerModal } from 'products/workflows/frontend/Workflows/EmailViewerModal'
import { MessageAsset } from 'products/workflows/frontend/Workflows/messageAssetsApi'

import { personPushNotificationsLogic } from './personPushNotificationsLogic'

const HedgehogGreek = pngHoggie(greekPng)

interface PersonPushNotificationsTabProps {
    teamId: number
    personId: string
}

function EmptyPushNotifications(): JSX.Element {
    return (
        <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
            <HedgehogGreek width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">No push notifications sent to this person</h2>
            <p className="text-sm text-balance text-tertiary">
                Once a workflow sends this person a push notification, it will show up here. Notifications only appear
                once a device took delivery.
            </p>
        </div>
    )
}

export function PersonPushNotificationsTab({ teamId, personId }: PersonPushNotificationsTabProps): JSX.Element {
    const logic = personPushNotificationsLogic({ teamId, personId })
    const { pushNotifications, pushNotificationsLoading } = useValues(logic)
    const [selected, setSelected] = useState<MessageAsset | null>(null)

    return (
        <>
            <LemonTable
                loading={pushNotificationsLoading}
                dataSource={pushNotifications}
                onRow={(asset: MessageAsset) => ({
                    onClick: () => setSelected(asset),
                    className: 'cursor-pointer',
                })}
                emptyState={<EmptyPushNotifications />}
                columns={[
                    {
                        title: 'Title',
                        dataIndex: 'subject',
                        key: 'subject',
                    },
                    {
                        title: 'Workflow',
                        key: 'function_id',
                        render: (_, asset: MessageAsset) => (
                            <Link
                                to={`${urls.workflow(asset.function_id, 'workflow')}?assetInvocation=${encodeURIComponent(
                                    asset.invocation_id
                                )}`}
                                onClick={(e) => e.stopPropagation()}
                            >
                                {asset.function_name || asset.function_id}
                            </Link>
                        ),
                    },
                    {
                        title: 'Sent',
                        key: 'sent_at',
                        render: (_, asset: MessageAsset) => <TZLabel time={asset.sent_at} />,
                    },
                ]}
            />
            <EmailViewerModal
                workflowId={selected?.function_id ?? ''}
                invocationId={selected?.invocation_id ?? ''}
                actionId={selected?.action_id ?? ''}
                isOpen={!!selected}
                onClose={() => setSelected(null)}
                title={selected?.subject || 'Push notification'}
                description={undefined}
            />
        </>
    )
}
