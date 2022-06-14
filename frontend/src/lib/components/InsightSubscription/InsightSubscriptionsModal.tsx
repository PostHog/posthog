import React from 'react'
import { InsightShortId } from '~/types'
import { LemonModal } from 'lib/components/LemonModal'
import { ManageSubscriptions } from './views/ManageSubscriptions'
import { EditSubscription } from './views/EditSubscription'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonButton, LemonButtonWithPopup } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'

export interface InsightSubscriptionsModalProps {
    visible: boolean
    closeModal: () => void
    insightShortId?: InsightShortId
    dashboardId?: number
    subscriptionId: number | 'new' | null
}

export interface SubscribeButtonProps {
    insightShortId?: InsightShortId
    dashboardId?: number
}

const urlForSubscriptions = ({ dashboardId, insightShortId }: SubscribeButtonProps): string => {
    if (insightShortId) {
        return urls.insightSubcriptions(insightShortId)
    } else if (dashboardId) {
        return urls.dashboardSubcriptions(dashboardId)
    }
    return ''
}

const urlForSubscription = (id: number | 'new', { dashboardId, insightShortId }: SubscribeButtonProps): string => {
    console.log({ dashboardId, insightShortId })
    if (insightShortId) {
        return urls.insightSubcription(insightShortId, id.toString())
    } else if (dashboardId) {
        return urls.dashboardSubcription(dashboardId, id.toString())
    }
    return ''
}

export function InsightSubscriptionsModal(props: InsightSubscriptionsModalProps): JSX.Element {
    const { visible, closeModal, dashboardId, subscriptionId } = props
    const { push } = useActions(router)

    const { insight } = useValues(insightLogic({ dashboardItemId: props.insightShortId, doNotLoad: true }))

    if (props.insightShortId && !insight.id) {
        return <></>
    }

    return (
        <>
            <LemonModal onCancel={closeModal} afterClose={closeModal} visible={visible} width={650}>
                {!subscriptionId ? (
                    <ManageSubscriptions
                        insightId={insight.id}
                        dashboardId={dashboardId}
                        onCancel={closeModal}
                        onSelect={(id) => push(urlForSubscription(id, props))}
                    />
                ) : (
                    <EditSubscription
                        id={subscriptionId}
                        insightId={insight.id}
                        dashboardId={dashboardId}
                        onCancel={() => push(urlForSubscriptions(props))}
                        onDelete={() => push(urlForSubscriptions(props))}
                    />
                )}
            </LemonModal>
        </>
    )
}

export function SubscribeButton(props: SubscribeButtonProps): JSX.Element {
    const { push } = useActions(router)

    return (
        <LemonButtonWithPopup
            type="stealth"
            fullWidth
            popup={{
                actionable: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <LemonButton onClick={() => push(urlForSubscription('new', props))} type="stealth" fullWidth>
                            New subscription
                        </LemonButton>
                        <LemonButton onClick={() => push(urlForSubscriptions(props))} type="stealth" fullWidth>
                            Manage subscriptions
                        </LemonButton>
                    </>
                ),
            }}
        >
            Subscribe
        </LemonButtonWithPopup>
    )
}
