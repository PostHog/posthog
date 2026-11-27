import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo } from 'react'

import { IconArrowRight, IconWrench } from '@posthog/icons'
import { LemonSelect, LemonSelectSection, LemonTag } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationType } from '~/types'

import { MODE_DEFINITIONS, ToolDefinition, getDefaultTools, getToolsForMode } from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'
import { type ModeChoiceSection, type ModeValue, getModeChoices } from '../modeChoices'

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
                choice.value === AgentMode.Research ? (
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
    disabledReason?: string
    onChange: (value: ModeValue) => void
}

/** The modes that the current feature flags allow. Research mode is offered only before the first message. */
export function useModeChoices(hasExistingMessages: boolean): ModeChoiceSection[] {
    const { featureFlags } = useValues(featureFlagLogic)
    return useMemo(() => getModeChoices(featureFlags, hasExistingMessages), [featureFlags, hasExistingMessages])
}

/**
 * The mode selector's state, shared by its lemon and quill skins: which modes are offered, which is
 * selected, why the control may be disabled, and the change handler with its telemetry.
 */
export function useModeSelector(): ModeSelectorController {
    const { agentMode, contextDisabledReason, conversation, threadMessageCount } = useValues(maxThreadLogic)
    const { setAgentMode } = useActions(maxThreadLogic)
    const sections = useModeChoices(threadMessageCount > 0)

    const onChange = useCallback(
        (value: ModeValue): void => {
            posthog.capture('phai mode switched', {
                previous_mode: agentMode,
                new_mode: value,
            })
            setAgentMode(value)
        },
        [agentMode, setAgentMode]
    )

    const isDeepResearch = conversation?.type === ConversationType.DeepResearch

    return {
        value: isDeepResearch ? AgentMode.Research : agentMode,
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
