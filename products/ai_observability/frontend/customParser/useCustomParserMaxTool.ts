import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { teamLogic } from 'scenes/teamLogic'

import { llmAnalyticsParserRecipesCreate } from '../generated/api'
import { parserRecipesLogic } from '../settings/parserRecipesLogic'
import { sampleForContext } from './sampleForContext'
import { handleCreateParserRecipeCall } from './validateRecipe'

const MAX_EXISTING_RECIPES_CONTEXT_LENGTH = 4000

export interface CustomParserMaxToolOptions {
    eventId: string
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
    input,
    output,
    tools,
    inputRecognized,
    outputRecognized,
    isLoading,
    isGeneration,
}: CustomParserMaxToolOptions): (() => void) | null {
    const customParsersEnabled = useFeatureFlag('LLM_ANALYTICS_CUSTOM_PARSERS')
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
    const active = customParsersEnabled && unrecognized !== null && !isLoading

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

    const { openMax } = useMaxTool({
        identifier: 'create_ai_trace_parser',
        active,
        context,
        clientExecution: validateAndSave,
        initialMaxPrompt: '!Set up a custom parser so this event displays properly',
    })

    return openMax
}
