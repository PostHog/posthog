import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import type { maxAutoPinLogicType } from './maxAutoPinLogicType'

const AUTO_PIN_STORAGE_KEY = 'max-ai-auto-pinned'

export const maxAutoPinLogic = kea<maxAutoPinLogicType>([
    path(['scenes', 'max', 'maxAutoPinLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], sceneLogic, ['tabs']],
        actions: [sceneLogic, ['pinTab']],
    })),
    actions({
        checkAndAutoPinAiTab: true,
        markAiTabAsAutoPinned: true,
    }),
    reducers({
        hasAutoPinnedAiTab: [
            false,
            { persist: true, storageKey: AUTO_PIN_STORAGE_KEY },
            {
                markAiTabAsAutoPinned: () => true,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        checkAndAutoPinAiTab: () => {
            const isAiFirst = values.featureFlags[FEATURE_FLAGS.AI_FIRST_EXPERIENCE]

            // Only auto-pin if:
            // 1. Feature flag is enabled
            // 2. We haven't auto-pinned before
            if (!isAiFirst || values.hasAutoPinnedAiTab) {
                return
            }

            // Find the AI tab if it exists
            const aiTab = values.tabs.find((tab) => tab.pathname === urls.ai() || tab.pathname.startsWith('/ai'))

            if (aiTab && !aiTab.pinned) {
                actions.pinTab(aiTab.id)
                actions.markAiTabAsAutoPinned()
            }
        },
    })),
    afterMount(({ actions }) => {
        // Check on mount and after a short delay to ensure tabs are loaded
        window.setTimeout(() => actions.checkAndAutoPinAiTab(), 500)
    }),
])
