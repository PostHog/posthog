import { connect, events, kea, path } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { attachedContextLogic } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { maxContextLogic } from './maxContextLogic'
import { MaxContextItem } from './maxTypes'
import type { posthogAiContextBridgeLogicType } from './posthogAiContextBridgeLogicType'

const BRIDGE_PROVIDER_ID = 'max-scene-bridge'

/**
 * Projects the active scene's rich `MaxContextItem[]` down to the flat `AttachedContextItem[]` the new
 * PostHog AI surface consumes. The `MaxContextType` string values (`'insight'`, `'dashboard'`, …) map
 * straight onto `type`; `id → key`, `name → label`. Same mapping shape as `projectToAttachedContext`.
 */
function projectSceneContext(sceneContext: MaxContextItem[]): AttachedContextItem[] {
    return sceneContext.map((item) => ({
        type: item.type,
        key: item.id,
        label: item.name ?? undefined,
    }))
}

/**
 * Coexistence bridge (old → new): mirrors `maxContextLogic.sceneContext` into the new
 * `attachedContextLogic` store so the sandbox side-panel runner sees the active scene's context with
 * zero product-scene edits. Lives in `scenes/max` and is deleted wholesale with it. Mount it from the
 * Max host that renders the sandbox side-panel runner (alongside `maxGlobalLogic`).
 */
export const posthogAiContextBridgeLogic = kea<posthogAiContextBridgeLogicType>([
    path(['scenes', 'max', 'posthogAiContextBridgeLogic']),
    connect(() => ({
        values: [maxContextLogic, ['sceneContext']],
        actions: [attachedContextLogic, ['registerContext', 'deregisterContext']],
    })),
    subscriptions(({ actions }) => ({
        sceneContext: (sceneContext: MaxContextItem[]) => {
            actions.registerContext(BRIDGE_PROVIDER_ID, projectSceneContext(sceneContext))
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.registerContext(BRIDGE_PROVIDER_ID, projectSceneContext(values.sceneContext))
        },
        beforeUnmount: () => {
            actions.deregisterContext(BRIDGE_PROVIDER_ID)
        },
    })),
])
