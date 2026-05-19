import { router } from 'kea-router'
import { useState } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { EditSubscription } from 'lib/components/Subscriptions/views/EditSubscription'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

/**
 * Parent-less subscription form — used for AI-prompt subscriptions which have no
 * insight or dashboard FK. Mounted as a full-page modal at `/subscriptions/new`
 * and `/subscriptions/:id/edit`. Insight- and dashboard-scoped subscriptions
 * still create/edit via the kebab-menu modal on their parent resource.
 *
 * URL `:subscriptionId` arrives as a raw prop on the component (see
 * `activeSceneComponentParamsWithTabId` in sceneLogic.tsx — components get raw
 * `sceneParams.params`, NOT the output of `paramsToProps`). The latter is only
 * applied to keyed kea logics, which this scene doesn't have.
 */
export function SubscriptionFormScene({ subscriptionId }: { subscriptionId?: string }): JSX.Element {
    const id: number | 'new' = subscriptionId ? Number(subscriptionId) : 'new'
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
