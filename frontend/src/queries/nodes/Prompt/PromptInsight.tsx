import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { castAssistantQuery } from 'scenes/max/utils'

import { Query } from '~/queries/Query/Query'
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    DataVisualizationNode,
    InsightVizNode,
    NodeKind,
    PromptQuery,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isHogQLQuery, isInsightQueryNode, isInsightVizNode } from '~/queries/utils'

const PROMPT_MAX_LENGTH = 4000

export interface PromptInsightProps {
    query: PromptQuery
    setQuery?: (query: PromptQuery) => void
    context?: QueryContext
    readOnly?: boolean
    embedded?: boolean
}

/** Wrap an AI-generated query into the viz node we can snapshot and render. */
function toGeneratedQuery(
    toolOutput: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
): InsightVizNode | DataVisualizationNode | null {
    const source = castAssistantQuery(toolOutput)
    if (!source) {
        return null
    }
    if (isHogQLQuery(source)) {
        return { kind: NodeKind.DataVisualizationNode, source } satisfies DataVisualizationNode
    }
    if (isInsightQueryNode(source)) {
        return { kind: NodeKind.InsightVizNode, source } satisfies InsightVizNode
    }
    return null
}

/**
 * Renders a "prompt" insight: a free-text prompt plus a snapshot of the last AI-generated viz.
 * The snapshot reuses the whole existing viz stack via `<Query>`; refining the insight is handed
 * off to Max (the `create_insight` tool), whose result is written back as the new snapshot.
 */
export function PromptInsight({ query, setQuery, context, readOnly, embedded }: PromptInsightProps): JSX.Element {
    const [draftPrompt, setDraftPrompt] = useState(query.prompt ?? '')

    const generatedQuery = query.generatedQuery ?? null
    const currentSource = isInsightVizNode(generatedQuery) ? generatedQuery.source : undefined

    const { openMax } = useMaxTool({
        identifier: 'create_insight',
        active: !readOnly,
        context: { current_query: currentSource },
        initialMaxPrompt: draftPrompt,
        callback: (
            toolOutput: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
        ) => {
            const node = toGeneratedQuery(toolOutput)
            if (!node) {
                return
            }
            setQuery?.({ ...query, prompt: draftPrompt, generatedQuery: node })
        },
    })

    const onGenerate = (): void => {
        // Persist the prompt before opening Max so it survives a reload, then hand off to the chat.
        if (draftPrompt !== query.prompt) {
            setQuery?.({ ...query, prompt: draftPrompt })
        }
        openMax?.()
    }

    return (
        <div className="flex flex-col gap-4">
            {!readOnly && (
                <div className="flex flex-col gap-2 rounded border p-4 bg-surface-primary">
                    <label className="flex items-center gap-1 font-semibold" htmlFor="prompt-insight-input">
                        <IconSparkles className="text-ai" /> Describe the insight you want
                    </label>
                    <LemonTextArea
                        id="prompt-insight-input"
                        value={draftPrompt}
                        onChange={setDraftPrompt}
                        maxLength={PROMPT_MAX_LENGTH}
                        minRows={2}
                        placeholder="e.g. Weekly active users over the last 90 days, broken down by country"
                        data-attr="prompt-insight-input"
                    />
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            icon={<IconSparkles />}
                            onClick={onGenerate}
                            disabledReason={
                                openMax
                                    ? draftPrompt.trim()
                                        ? undefined
                                        : 'Enter a prompt first'
                                    : 'Max is unavailable'
                            }
                            data-attr="prompt-insight-generate"
                        >
                            {generatedQuery ? 'Refine with Max' : 'Generate with Max'}
                        </LemonButton>
                    </div>
                </div>
            )}
            {generatedQuery ? (
                <Query query={generatedQuery} readOnly embedded={embedded} context={context} />
            ) : (
                readOnly && (
                    <div className="flex flex-col items-center gap-2 rounded border border-dashed p-8 text-secondary">
                        <IconSparkles className="text-2xl text-ai" />
                        <span>This prompt insight has no generated chart yet.</span>
                    </div>
                )
            )}
        </div>
    )
}
