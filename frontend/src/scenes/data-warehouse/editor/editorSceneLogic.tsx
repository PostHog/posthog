import { actions, kea, listeners, path, props } from 'kea'
import posthog from 'posthog-js'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import type { editorSceneLogicType } from './editorSceneLogicType'

export const renderTableCount = (count: undefined | number): null | JSX.Element => {
    if (!count) {
        return null
    }

    return (
        <span className="text-xs mr-1 italic text-[color:var(--color-text-secondary-3000)]">
            {`(${new Intl.NumberFormat('en', {
                notation: 'compact',
                compactDisplay: 'short',
            })
                .format(count)
                .toLowerCase()})`}
        </span>
    )
}

export interface EditorSceneLogicProps {
    tabId: string
}

export const editorSceneLogic = kea<editorSceneLogicType>([
    path(['data-warehouse', 'editor', 'editorSceneLogic']),
    props({} as EditorSceneLogicProps),
    tabAwareScene(),
    actions({
        reportAIQueryPrompted: true,
        reportAIQueryAccepted: true,
        reportAIQueryRejected: true,
        reportAIQueryPromptOpen: true,
    }),
    listeners(() => ({
        reportAIQueryPrompted: () => {
            posthog.capture('ai_query_prompted')
        },
        reportAIQueryAccepted: () => {
            posthog.capture('ai_query_accepted')
        },
        reportAIQueryRejected: () => {
            posthog.capture('ai_query_rejected')
        },
        reportAIQueryPromptOpen: () => {
            posthog.capture('ai_query_prompt_open')
        },
    })),
])
