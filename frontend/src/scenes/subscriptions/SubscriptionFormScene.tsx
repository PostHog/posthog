import { router } from 'kea-router'
import { useState } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { EditSubscription } from 'lib/components/Subscriptions/views/EditSubscription'
import { SceneExport, type SceneProps } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

/**
 * Parent-less subscription form — used for AI-prompt subscriptions which have no
 * insight or dashboard FK. Mounted as a full-page modal at `/subscriptions/new`
 * and `/subscriptions/:id/edit`. Insight- and dashboard-scoped subscriptions
 * still create/edit via the kebab-menu modal on their parent resource.
 */
export function SubscriptionFormScene(props: SceneProps): JSX.Element {
    const subscriptionId = props.params?.subscriptionId
    const id = subscriptionId ? Number(subscriptionId) : 'new'
    // Local open-state so the modal animates out before the scene unmounts.
    // Without this, the portal tears down at the same React tick as the route
    // change → `removeChild` reconciliation error during commit cleanup.
    const [isOpen, setIsOpen] = useState(true)
    const goBack = (): void => {
        setIsOpen(false)
        // Match LemonModal's CSS transition duration (200ms) — the cleanup runs
        // after the leave animation finishes.
        window.setTimeout(() => router.actions.push(urls.subscriptions()), 200)
    }
    return (
        <SceneContent>
            <LemonModal isOpen={isOpen} onClose={goBack} simple={false} width={650}>
                <EditSubscription id={id} onCancel={goBack} onDelete={goBack} />
            </LemonModal>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: SubscriptionFormScene,
}
