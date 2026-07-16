import { connect, kea, path } from 'kea'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { maxGlobalLogic } from './maxGlobalLogic'
import type { phaiAiComposerSeedLogicType } from './phaiAiComposerSeedLogicType'

/**
 * Forwards the existing `/ai?ask=...` deep link into the new task composer. This logic is mounted only while
 * the new PostHog AI view is rendered, leaving the legacy `maxLogic` query handling unchanged.
 */
export const phaiAiComposerSeedLogic = kea<phaiAiComposerSeedLogicType>([
    path(['scenes', 'max', 'phaiAiComposerSeedLogic']),

    connect({
        values: [maxGlobalLogic, ['dataProcessingAccepted']],
        actions: [composerSeedLogic, ['setSeed']],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.ai()]: (_, search) => {
            if (search.ask && !search.chat) {
                // `ask` is URL-controlled — same org-level AI data-processing consent gate as the legacy
                // `askMax` path: without approval the seed only prefills the composer, and the user's own
                // send goes through the composer's consent flow.
                actions.setSeed({ prompt: String(search.ask), autoSubmit: values.dataProcessingAccepted })
            }
        },
    })),
])
