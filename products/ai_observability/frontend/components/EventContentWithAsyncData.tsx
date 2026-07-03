import { useValues } from 'kea'
import React from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    ConversationDisplayOption,
    ConversationMessagesDisplay,
} from '../ConversationDisplay/ConversationMessagesDisplay'
import { useCustomParserMaxTool } from '../customParser/useCustomParserMaxTool'
import { useAIData } from '../hooks/useAIData'
import { normalizeMessage, normalizeMessages } from '../messageNormalization'
import type { GenerationSentiment } from '../sentimentResults'
import { parserRecipesLogic } from '../settings/parserRecipesLogic'
import { AIDataLoading } from './AIDataLoading'
import { JSONValueDisplay } from './JSONValueDisplay'

interface EventContentConversationProps {
    eventId: string
    traceId?: string | null
    timestamp?: string
    rawInput: unknown
    rawOutput: unknown
    tools?: unknown
    errorData?: unknown
    httpStatus?: unknown
    raisedError?: boolean
    searchQuery?: string
    displayOption?: ConversationDisplayOption
    /** Original $ai_input index to auto-expand (e.g. from sentiment tab deep link) */
    highlightMessageIndex?: number | null
    /** Generation id for per-message sentiment lookups; only generations have sentiment. */
    generationEventId?: string
    generationSentiment?: GenerationSentiment | null
}

// Renders an event's input/output, routing to one of two renderers: the chat UI
// when recipes recognize both sides as a conversation, or a raw JSON view
// otherwise. One path for generations, spans, and embeddings.
export function EventContentConversation({
    eventId,
    traceId,
    timestamp,
    rawInput,
    rawOutput,
    tools,
    errorData,
    httpStatus,
    raisedError,
    searchQuery,
    displayOption,
    highlightMessageIndex,
    generationEventId,
    generationSentiment,
}: EventContentConversationProps): JSX.Element {
    const {
        input,
        output,
        tools: loadedTools,
        isLoading,
    } = useAIData({
        uuid: eventId,
        input: rawInput,
        output: rawOutput,
        tools,
        traceId: traceId ?? undefined,
        timestamp,
    })
    // The normalizer is a module singleton — recipesVersion signals the memos below are stale
    const { recipesVersion } = useValues(parserRecipesLogic)

    // Map each normalized input message back to its original index in $ai_input,
    // a stable key for per-message sentiment lookups. Generations only.
    const inputSourceIndices = React.useMemo(() => {
        if (!generationEventId) {
            return undefined
        }
        const indices: number[] = []
        if (loadedTools) {
            indices.push(-1) // tools message prepended by normalizeMessages
        }
        if (Array.isArray(input)) {
            for (let i = 0; i < input.length; i++) {
                const expanded = normalizeMessage(input[i], 'user')
                for (let j = 0; j < expanded.length; j++) {
                    indices.push(i)
                }
            }
        }
        return indices
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [input, loadedTools, generationEventId, recipesVersion])

    const { recognized: inputRecognized, messages: inputMessages } = React.useMemo(
        () => normalizeMessages(input, 'user', loadedTools),
        // oxlint-disable-next-line react-hooks/exhaustive-deps
        [input, loadedTools, recipesVersion]
    )
    const { recognized: outputRecognized, messages: outputMessages } = React.useMemo(
        () => normalizeMessages(output, 'assistant'),
        // oxlint-disable-next-line react-hooks/exhaustive-deps
        [output, recipesVersion]
    )

    const openCustomParserMax = useCustomParserMaxTool({
        eventId,
        input,
        output,
        tools: loadedTools,
        inputRecognized,
        outputRecognized,
        isLoading,
        isGeneration: !!generationEventId,
    })

    if (isLoading) {
        return <AIDataLoading variant="block" />
    }

    if (!inputRecognized || !outputRecognized) {
        return (
            <JsonInputOutput
                input={input}
                output={output}
                errorData={errorData}
                raisedError={raisedError}
                onSetUpCustomParser={openCustomParserMax}
            />
        )
    }

    return (
        <ConversationMessagesDisplay
            inputNormalized={inputMessages}
            outputNormalized={outputMessages}
            inputSourceIndices={inputSourceIndices}
            errorData={errorData}
            httpStatus={typeof httpStatus === 'number' ? httpStatus : undefined}
            raisedError={raisedError}
            searchQuery={searchQuery}
            displayOption={displayOption}
            traceId={traceId}
            generationSentiment={generationSentiment}
            highlightMessageIndex={highlightMessageIndex}
        />
    )
}

// Raw renderer for input/output that no recipe recognized as a conversation.
function JsonInputOutput({
    input,
    output,
    errorData,
    raisedError,
    onSetUpCustomParser,
}: {
    input: unknown
    output: unknown
    errorData?: unknown
    raisedError?: boolean
    onSetUpCustomParser?: (() => void) | null
}): JSX.Element {
    // On error, surface the error payload when there's no output to show.
    const outputValue = raisedError ? (output ?? errorData) : output

    return (
        <div className="space-y-4">
            {onSetUpCustomParser && (
                <div className="flex items-center justify-between gap-2 px-2 py-1 border border-primary rounded bg-surface-secondary">
                    <span className="text-xs text-muted">
                        Shown as raw JSON — no parser recognizes this event's shape.
                    </span>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconSparkles />}
                        onClick={onSetUpCustomParser}
                        data-attr="llma-json-fallback-create-parser"
                    >
                        Set up custom parser with PostHog AI
                    </LemonButton>
                </div>
            )}
            <div>
                <h3 className="font-semibold mb-2">Input</h3>
                <div className="p-2 bg-surface-secondary rounded text-xs overflow-auto">
                    <JSONValueDisplay value={input} />
                </div>
            </div>
            <div>
                <h3 className="font-semibold mb-2">Output</h3>
                <div
                    className={`p-2 rounded text-xs overflow-auto ${
                        raisedError ? 'bg-danger-highlight' : 'bg-surface-secondary'
                    }`}
                >
                    <JSONValueDisplay value={outputValue} />
                </div>
            </div>
        </div>
    )
}
