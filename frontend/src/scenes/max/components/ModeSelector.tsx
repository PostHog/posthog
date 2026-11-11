import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo } from 'react'

import { IconArrowRight, IconWrench } from '@posthog/icons'
import { LemonSelect, LemonSelectSection, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationType } from '~/types'

import {
    MODE_DEFINITIONS,
    SPECIAL_MODES,
    SpecialMode,
    ToolDefinition,
    getDefaultTools,
    getToolsForMode,
} from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

export type ModeValue = AgentMode | SpecialMode | null

function buildModeTooltip(description: string, tools: ToolDefinition[]): JSX.Element {
    return (
        <div className="max-h-[calc(100vh - (var(--spacing) * 5))] overflow-y-auto show-scrollbar-on-hover flex flex-col gap-1.5">
            <div>{description}</div>
            {tools.length > 0 && (
                <div>
                    <div className="font-semibold mb-0.5">Tools:</div>
                    <ul className="space-y-0.5 text-sm *:flex *:items-start">
                        {tools.map((tool: ToolDefinition) => (
                            <li key={tool.name}>
                                <span className="flex text-base text-success shrink-0 ml-1 mr-2 h-[1.25em]">
                                    {tool.icon || <IconWrench />}
                                </span>
                                <span>
                                    <strong className="italic">
                                        {tool.name}
                                        {tool.beta && (
                                            <LemonTag size="small" type="warning" className="ml-1 not-italic">
                                                BETA
                                            </LemonTag>
                                        )}
                                        {tool.alpha && (
                                            <LemonTag size="small" type="danger" className="ml-1 not-italic">
                                                ALPHA
                                            </LemonTag>
                                        )}
                                    </strong>
                                    {tool.description?.replace(tool.name, '')}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

function buildGeneralTooltip(description: string, defaultTools: ToolDefinition[]): JSX.Element {
    const modeEntries = Object.entries(MODE_DEFINITIONS) as [
        AgentMode,
        (typeof MODE_DEFINITIONS)[keyof typeof MODE_DEFINITIONS],
    ][]

    return (
        <div className="max-w-sm flex flex-col gap-1.5">
            <div>{description}</div>
            {defaultTools.length > 0 && (
                <div>
                    <div className="font-semibold mb-0.5">Default tools:</div>
                    <ul className="space-y-0.5 text-sm *:flex *:items-start">
                        {defaultTools.map((tool: ToolDefinition) => (
                            <li key={tool.name}>
                                <span className="flex text-base text-success shrink-0 ml-1 mr-2 h-[1.25em]">
                                    {tool.icon || <IconWrench />}
                                </span>
                                <span>{tool.name}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {modeEntries.length > 0 && (
                <div>
                    <div className="font-semibold mb-0.5">Mode-specific tools:</div>
                    <ul className="space-y-0.5 text-sm *:flex *:items-start">
                        {modeEntries.map(([mode, def]) => {
                            const tools = getToolsForMode(mode)
                            if (tools.length === 0) {
                                return null
                            }
                            return (
                                <li key={mode}>
                                    <IconArrowRight className="text-base text-secondary shrink-0 ml-1 mr-2 h-[1.25em]" />
                                    <span>
                                        <em>{def.name}:</em> {tools.map((tool) => tool.name).join(', ')}
                                    </span>
                                </li>
                            )
                        })}
                    </ul>
                </div>
            )}
        </div>
    )
}

interface GetModeOptionsParams {
    planModeEnabled: boolean
    researchEnabled: boolean
    featureFlags: Record<string, boolean | string>
    hasExistingMessages: boolean
}

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

function getModeChoices({
    planModeEnabled,
    researchEnabled,
    featureFlags,
    hasExistingMessages,
}: GetModeOptionsParams): ModeChoiceSection[] {
    const specialOptions: ModeChoice[] = [
        {
            value: null,
            name: SPECIAL_MODES.auto.name,
            description: SPECIAL_MODES.auto.description,
            icon: SPECIAL_MODES.auto.icon,
            tools: getDefaultTools(),
        },
    ]
    if (planModeEnabled) {
        specialOptions.push({
            value: 'plan',
            name: SPECIAL_MODES.plan.name,
            description: SPECIAL_MODES.plan.description,
            icon: SPECIAL_MODES.plan.icon,
            beta: SPECIAL_MODES.plan.beta,
            tools: getDefaultTools(),
        })
    }

    if (researchEnabled && !hasExistingMessages) {
        specialOptions.push({
            value: 'research',
            name: SPECIAL_MODES.research.name,
            description: SPECIAL_MODES.research.description,
            icon: SPECIAL_MODES.research.icon,
            beta: SPECIAL_MODES.research.beta,
            tools: [],
        })
    }

    const modeEntries = Object.entries(MODE_DEFINITIONS).filter(([_, def]) => {
        if (def.flag && !featureFlags[FEATURE_FLAGS[def.flag]]) {
            return false
        }
        return true
    })

    return [
        { options: specialOptions },
        {
            options: modeEntries.map(([mode, def]) => ({
                value: mode as AgentMode,
                name: def.name,
                description: def.description,
                icon: def.icon,
                beta: def.beta,
                alpha: def.alpha,
                tools: getToolsForMode(mode as AgentMode),
            })),
        },
    ]
}

function toLemonSelectSections(sections: ModeChoiceSection[]): LemonSelectSection<ModeValue>[] {
    return sections.map((section) => ({
        options: section.options.map((choice) => ({
            value: choice.value,
            label:
                choice.beta || choice.alpha ? (
                    <span className="flex items-center gap-1">
                        {choice.name}
                        {choice.beta && (
                            <LemonTag size="small" type="warning">
                                BETA
                            </LemonTag>
                        )}
                        {choice.alpha && (
                            <LemonTag size="small" type="danger">
                                ALPHA
                            </LemonTag>
                        )}
                    </span>
                ) : (
                    choice.name
                ),
            icon: choice.icon,
            tooltip:
                choice.value === 'research' ? (
                    <div>{choice.description}</div>
                ) : (
                    buildModeTooltip(choice.description, choice.tools)
                ),
        })),
    }))
}

export interface ModeSelectorController {
    value: ModeValue
    sections: ModeChoiceSection[]
    disabledReason: string | undefined
    onChange: (value: ModeValue) => void
}

/**
 * The mode selector's state, shared by its lemon and quill skins: which modes are offered, which is
 * selected, why the control may be disabled, and the change handler with its telemetry.
 */
export function useModeSelector(): ModeSelectorController {
    const { agentMode, contextDisabledReason, conversation, threadMessageCount } = useValues(maxThreadLogic)
    const { setAgentMode } = useActions(maxThreadLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const researchEnabled = useFeatureFlag('MAX_DEEP_RESEARCH')
    const planModeEnabled = useFeatureFlag('PHAI_PLAN_MODE')

    const hasExistingMessages = threadMessageCount > 0
    const sections = useMemo(
        () =>
            getModeChoices({
                planModeEnabled,
                researchEnabled,
                featureFlags,
                hasExistingMessages,
            }),
        [planModeEnabled, researchEnabled, featureFlags, hasExistingMessages]
    )

    const onChange = useCallback(
        (value: ModeValue): void => {
            posthog.capture('phai mode switched', {
                previous_mode: agentMode,
                new_mode: value,
            })
            setAgentMode(value as AgentMode | null)
        },
        [agentMode, setAgentMode]
    )

    const isDeepResearch = conversation?.type === ConversationType.DeepResearch

    return {
        value: isDeepResearch ? 'research' : agentMode,
        sections,
        disabledReason: isDeepResearch
            ? "You're in research mode, start a new conversation to change mode"
            : contextDisabledReason,
        onChange,
    }
}

export function ModeSelector(): JSX.Element | null {
    const { value, sections, disabledReason, onChange } = useModeSelector()
    const modeOptions = useMemo(() => toLemonSelectSections(sections), [sections])

    return (
        <LemonSelect
            value={value}
            onChange={onChange}
            options={modeOptions}
            size="xxsmall"
            type="tertiary"
            disabledReason={disabledReason}
            tooltip={buildGeneralTooltip(
                'Select a mode to focus PostHog AI on a specific product or task. Each mode unlocks specialized capabilities, tools, and expertise.',
                getDefaultTools()
            )}
            dropdownPlacement="top-start"
            dropdownMatchSelectWidth={false}
            menu={{ className: 'min-w-48' }}
            className="flex-shrink-0 border [&>span]:text-secondary"
        />
    )
}
