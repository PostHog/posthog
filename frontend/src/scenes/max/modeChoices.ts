import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import { MODE_DEFINITIONS, SPECIAL_MODES, ToolDefinition, getDefaultTools, getToolsForMode } from './max-constants'

/** An agent mode, or `null` for auto mode. */
export type ModeValue = AgentMode | null

/** One mode the selector offers, as plain data so each skin draws it its own way. */
export interface ModeChoice {
    value: ModeValue
    name: string
    description: string
    icon: JSX.Element
    beta?: boolean
    alpha?: boolean
    /** The tools the lemon tooltip lists; empty for research mode, which has no tool list. */
    tools: ToolDefinition[]
}

export interface ModeChoiceSection {
    options: ModeChoice[]
}

/** The modes that the feature flags allow. Research mode is offered only before the first message. */
export function getModeChoices(featureFlags: FeatureFlagsSet, hasExistingMessages: boolean): ModeChoiceSection[] {
    const specialOptions: ModeChoice[] = [
        {
            value: null,
            name: SPECIAL_MODES.auto.name,
            description: SPECIAL_MODES.auto.description,
            icon: SPECIAL_MODES.auto.icon,
            tools: getDefaultTools(),
        },
    ]
    if (featureFlags[FEATURE_FLAGS.PHAI_PLAN_MODE]) {
        specialOptions.push({
            value: AgentMode.Plan,
            name: SPECIAL_MODES.plan.name,
            description: SPECIAL_MODES.plan.description,
            icon: SPECIAL_MODES.plan.icon,
            beta: SPECIAL_MODES.plan.beta,
            tools: getDefaultTools(),
        })
    }
    if (featureFlags[FEATURE_FLAGS.MAX_DEEP_RESEARCH] && !hasExistingMessages) {
        specialOptions.push({
            value: AgentMode.Research,
            name: SPECIAL_MODES.research.name,
            description: SPECIAL_MODES.research.description,
            icon: SPECIAL_MODES.research.icon,
            beta: SPECIAL_MODES.research.beta,
            tools: [],
        })
    }

    const modeEntries = (
        Object.entries(MODE_DEFINITIONS) as [AgentMode, (typeof MODE_DEFINITIONS)[keyof typeof MODE_DEFINITIONS]][]
    ).filter(([_, def]) => !def.flag || featureFlags[FEATURE_FLAGS[def.flag]])

    return [
        { options: specialOptions },
        {
            options: modeEntries.map(([mode, def]) => ({
                value: mode,
                name: def.name,
                description: def.description,
                icon: def.icon,
                beta: def.beta,
                alpha: def.alpha,
                tools: getToolsForMode(mode),
            })),
        },
    ]
}

/**
 * Reads an agent mode from a link or a `mode=` command. Only a mode the picker would offer at the start of a
 * conversation is accepted; anything else gives auto mode (`null`).
 */
export function agentModeFromParam(value: string, featureFlags: FeatureFlagsSet): ModeValue {
    for (const section of getModeChoices(featureFlags, false)) {
        const choice = section.options.find((option) => option.value === value)
        if (choice) {
            return choice.value
        }
    }
    return null
}
