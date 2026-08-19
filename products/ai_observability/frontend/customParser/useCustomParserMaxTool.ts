import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { lemonToast } from '@posthog/lemon-ui'
import { handleCreateParserRecipeCall, sampleForContext } from '@posthog/llm-normalizer'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { teamLogic } from 'scenes/teamLogic'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { llmAnalyticsParserRecipesCreate } from '../generated/api'
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
    input: unknown
    output: unknown
    tools?: unknown
    inputRecognized: boolean
    outputRecognized: boolean
    isLoading: boolean
    isGeneration: boolean
}

/**
 * Registers the create_ai_trace_parser Max tool for an event that fell back to raw JSON.
 * The clientExecution handler validates the agent's YAML against this exact event, saves it
 * on success, and resumes the conversation with the verdict. Returns openMax (null while inactive).
 */
export function useCustomParserMaxTool({
    eventId,
    traceId,
    input,
    output,
    tools,
    inputRecognized,
    outputRecognized,
    isLoading,
    isGeneration,
}: CustomParserMaxToolOptions): (() => void) | null {
    const { currentTeamId } = useValues(teamLogic)
    const { storedForMerge, customItems } = useValues(parserRecipesLogic)
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
            event_uuid: eventId,
            event_type: isGeneration ? 'generation' : 'span',
            unrecognized,
            sample_input: sampleForContext(input),
            sample_output: sampleForContext(output),
            existing_recipes: existingBlocks.length > 0 ? existingBlocks.join('\n') : '(none)',
        }
    }, [active, eventId, isGeneration, unrecognized, input, output, customItems])

    const validateAndSave = useCallback(
        async (args: Record<string, any>): Promise<Record<string, unknown>> =>
            handleCreateParserRecipeCall(args, {
                eventId,
                existingRecipes: storedForMerge,
                sample: { input, output, tools, inputRecognized, outputRecognized },
                saveRecipe: async (name, source) => {
                    const created = await llmAnalyticsParserRecipesCreate(String(currentTeamId), { name, source })
                    // Reloading applies the recipe to the live normalizer, re-rendering the open trace
                    loadRecipes()
                    lemonToast.success(`Custom parser "${name}" saved`)
                    return created.id
                },
            }),
        [eventId, storedForMerge, input, output, tools, inputRecognized, outputRecognized, currentTeamId, loadRecipes]
    )

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
        clientExecution: validateAndSave,
        initialMaxPrompt: '!Set up a custom parser so this event displays properly',
    })

    return openMax
}
