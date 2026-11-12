import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { lemonToast } from '@posthog/lemon-ui'
import { sampleForContext } from '@posthog/llm-normalizer'

import { useMaxTool } from 'scenes/max/useMaxTool'

import type { AttachedContextItem } from '~/layout/ai/attachedContext'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { parserRecipesLogic } from '../settings/parserRecipesLogic'

const MAX_EXISTING_RECIPES_CONTEXT_LENGTH = 4000

// Static, trusted instruction — never interpolate user or ingested trace data into it.
// Points the headless agent at the reference + create tools and the trace_id/event_uuid it
// finds in the untrusted trace-event sample block.
const AI_TRACE_PARSER_TOOL_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The user has an LLM trace event open that fell back to raw JSON because no parser recognized it. ' +
        'To fix it, first call llma-parser-recipe-reference for the recipe DSL syntax and examples, then call ' +
        'llma-parser-recipe-create with the trace_id and event_uuid from the attached trace event sample. The ' +
        'samples in context are truncated, but the server compiles and validates your recipe against the full ' +
        'event and only saves it when it works. The open trace re-renders once the recipe is saved.',
}

export interface CustomParserMaxToolOptions {
    eventId: string
    traceId?: string | null
    timestamp?: string
    input: unknown
    output: unknown
    inputRecognized: boolean
    outputRecognized: boolean
    isLoading: boolean
    isGeneration: boolean
}

/**
 * Registers the create_ai_trace_parser Max tool for an event that fell back to raw JSON.
 * The server tests the agent's YAML against the event and saves it when it parses it; the
 * callback then reloads the team's recipes so the open trace re-renders. Returns openMax (null while inactive).
 */
export function useCustomParserMaxTool({
    eventId,
    traceId,
    timestamp,
    input,
    output,
    inputRecognized,
    outputRecognized,
    isLoading,
    isGeneration,
}: CustomParserMaxToolOptions): (() => void) | null {
    const { customItems } = useValues(parserRecipesLogic)
    const { loadRecipes } = useActions(parserRecipesLogic)

    const unrecognized =
        !inputRecognized && !outputRecognized
            ? 'both'
            : !inputRecognized
              ? 'input'
              : !outputRecognized
                ? 'output'
                : null
    const active = unrecognized !== null && !isLoading

    const context = useMemo(() => {
        if (!active) {
            return undefined
        }
        // Truncate on recipe boundaries — a mid-recipe cut would put broken YAML in the prompt
        const existingBlocks: string[] = []
        let remainingBudget = MAX_EXISTING_RECIPES_CONTEXT_LENGTH
        let omittedCount = 0
        for (const item of customItems) {
            const block = `--- ${item.name} ---\n${item.source}`
            if (block.length <= remainingBudget) {
                existingBlocks.push(block)
                remainingBudget -= block.length
            } else {
                omittedCount += 1
            }
        }
        if (omittedCount > 0) {
            existingBlocks.push(`… (${omittedCount} more recipes omitted for length)`)
        }
        return {
            trace_id: traceId ?? null,
            trace_timestamp: timestamp ?? '(none)',
            event_uuid: eventId,
            event_type: isGeneration ? 'generation' : 'span',
            unrecognized,
            sample_input: sampleForContext(input),
            sample_output: sampleForContext(output),
            existing_recipes: existingBlocks.length > 0 ? existingBlocks.join('\n') : '(none)',
        }
    }, [active, traceId, timestamp, eventId, isGeneration, unrecognized, input, output, customItems])

    useAttachedContext(
        active
            ? [
                  AI_TRACE_PARSER_TOOL_CONTEXT_ITEM,
                  { type: 'llm_trace_event', key: eventId },
                  {
                      type: 'ai_trace_parser_context',
                      value: JSON.stringify({
                          trace_id: traceId ?? null,
                          event_uuid: eventId,
                          event_type: isGeneration ? 'generation' : 'span',
                          unrecognized,
                          sample_input: sampleForContext(input),
                          sample_output: sampleForContext(output),
                      }),
                      label: 'Trace event sample',
                  },
              ]
            : null
    )

    // Headless mirror: when the agent's llma-parser-recipe-create tool completes, reload the team's
    // recipes so the live normalizer re-renders the open trace. loadRecipes is idempotent, so we run
    // it on every completion regardless of whether the tool actually saved.
    useMcpToolApplyBack({
        tools: ['llma-parser-recipe-create'],
        targetKey: 'ai-trace-parser',
        active,
        onApply: (event, { innerInput }) => {
            loadRecipes()
            // A create for a different event must not claim this one was fixed; when the
            // args are unparseable we keep the toast, matching the pre-innerInput behavior.
            if (innerInput && typeof innerInput.event_uuid === 'string' && innerInput.event_uuid !== eventId) {
                return
            }
            try {
                const output = event.invocation.output
                const serialized = typeof output === 'string' ? output : JSON.stringify(output)
                if (serialized && serialized.includes('recipe_id')) {
                    lemonToast.success('Custom parser saved')
                }
            } catch {
                // Output shape is client-profile-dependent — the agent narrates failures in chat.
            }
        },
    })

    const { openMax } = useMaxTool({
        identifier: 'create_ai_trace_parser',
        active,
        context,
        callback: (toolOutput: unknown) => {
            // Reloading applies the saved recipe to the live normalizer, re-rendering the open trace
            loadRecipes()
            if (toolOutput && typeof toolOutput === 'object' && 'recipe_id' in toolOutput && toolOutput.recipe_id) {
                lemonToast.success('Custom parser saved')
            }
        },
        initialMaxPrompt: '!Set up a custom parser so this event displays properly',
    })

    return openMax
}
