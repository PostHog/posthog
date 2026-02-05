import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo } from 'react'

import { IconArrowRight, IconWrench } from '@posthog/icons'
import { LemonSelect, LemonSelectSection, LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { identifierToHuman } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationType } from '~/types'

import {
    MODE_DEFINITIONS,
    SPECIAL_MODES,
    SpecialMode,
    TOOL_DEFINITIONS,
    ToolDefinition,
    getDefaultTools,
    getToolsForMode,
} from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

type ModeValue = AgentMode | SpecialMode | null

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
    // Group tools by their product (Scene), excluding some scenes
    const excludedScenes = [Scene.Insight, Scene.SQLEditor, Scene.Replay]
    const toolsByProduct = Object.values(TOOL_DEFINITIONS).reduce(
        (acc, tool) => {
            if (!tool.product || excludedScenes.includes(tool.product)) {
                return acc
            }
            if (!acc[tool.product]) {
                acc[tool.product] = []
            }
            acc[tool.product]!.push(tool)
            return acc
        },
        {} as Partial<Record<Scene, ToolDefinition[]>>
    )

    return (
        <div className="max-h-[calc(100vh - (var(--spacing) * 5))] overflow-y-auto show-scrollbar-on-hover flex flex-col gap-1.5">
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
                                <span>
                                    <strong className="italic">
                                        {tool.name}
                                        {tool.beta && (
                                            <LemonTag size="small" type="warning" className="ml-1 not-italic">
                                                BETA
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
            {Object.keys(toolsByProduct).length > 0 && (
                <div>
                    <div className="font-semibold mb-0.5">Contextual tools:</div>
                    <ul className="space-y-0.5 text-sm *:flex *:items-start">
                        {Object.entries(toolsByProduct).map(([product, tools]) => (
                            <li key={product}>
                                <IconArrowRight className="text-base text-secondary shrink-0 ml-1 mr-2 h-[1.25em]" />
                                <span>
                                    <em>
                                        In {sceneConfigurations[product as Scene]?.name || identifierToHuman(product)}
                                        :{' '}
                                    </em>
                                    {tools.map((tool, index) => (
                                        <span key={tool.name}>
                                            <strong className="italic">
                                                {tool.name}
                                                {tool.beta && (
                                                    <LemonTag size="small" type="warning" className="ml-1 not-italic">
                                                        BETA
                                                    </LemonTag>
                                                )}
                                            </strong>
                                            {tool.description?.replace(tool.name, '')}
                                            {index < tools.length - 1 && <>; </>}
                                        </span>
                                    ))}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

interface GetModeOptionsParams {
    planModeEnabled: boolean
    researchEnabled: boolean
    webSearchEnabled: boolean
    errorTrackingModeEnabled: boolean
    surveyModeEnabled: boolean
    hasExistingMessages: boolean
    flagsModeEnabled: boolean
}

function getModeOptions({
    planModeEnabled,
    researchEnabled,
    webSearchEnabled,
    errorTrackingModeEnabled,
    surveyModeEnabled,
    hasExistingMessages,
    flagsModeEnabled,
}: GetModeOptionsParams): LemonSelectSection<ModeValue>[] {
    const specialOptions = [
        {
            value: null as ModeValue,
            label: SPECIAL_MODES.auto.name as string | JSX.Element,
            icon: SPECIAL_MODES.auto.icon,
            tooltip: buildModeTooltip(SPECIAL_MODES.auto.description, getDefaultTools({ webSearchEnabled })),
        },
    ]
    if (planModeEnabled) {
        specialOptions.push({
            value: 'plan' as ModeValue,
            label: (
                <span className="flex items-center gap-1">
                    {SPECIAL_MODES.plan.name}
                    {SPECIAL_MODES.plan.beta && (
                        <LemonTag size="small" type="warning">
                            BETA
                        </LemonTag>
                    )}
                </span>
            ),
            icon: SPECIAL_MODES.plan.icon,
            tooltip: buildModeTooltip(SPECIAL_MODES.plan.description, getDefaultTools({ webSearchEnabled })),
        })
    }

    if (researchEnabled && !hasExistingMessages) {
        specialOptions.push({
            value: 'research' as ModeValue,
            label: (
                <span className="flex items-center gap-1">
                    {SPECIAL_MODES.research.name}
                    {SPECIAL_MODES.research.beta && (
                        <LemonTag size="small" type="warning">
                            BETA
                        </LemonTag>
                    )}
                </span>
            ),
            icon: SPECIAL_MODES.research.icon,
            tooltip: <div>{SPECIAL_MODES.research.description}</div>,
        })
    }

    const modeEntries = Object.entries(MODE_DEFINITIONS).filter(([mode]) => {
        if (mode === AgentMode.ErrorTracking && !errorTrackingModeEnabled) {
            return false
        }
        if (mode === AgentMode.Survey && !surveyModeEnabled) {
            return false
        }
        if (mode === AgentMode.Flags && !flagsModeEnabled) {
            return false
        }
        return true
    })

    return [
        { options: specialOptions },
        {
            options: modeEntries.map(([mode, def]) => ({
                value: mode as AgentMode,
                label: def.beta ? (
                    <span className="flex items-center gap-1">
                        {def.name}
                        <LemonTag size="small" type="warning">
                            BETA
                        </LemonTag>
                    </span>
                ) : (
                    def.name
                ),
                icon: def.icon,
                tooltip: buildModeTooltip(def.description, getToolsForMode(mode as AgentMode)),
            })),
        },
    ]
}

export function ModeSelector(): JSX.Element | null {
    const { agentMode, contextDisabledReason, conversation, threadMessageCount } = useValues(maxThreadLogic)
    const { setAgentMode } = useActions(maxThreadLogic)
    const researchEnabled = useFeatureFlag('MAX_DEEP_RESEARCH')
    const planModeEnabled = useFeatureFlag('PHAI_PLAN_MODE')
    const webSearchEnabled = useFeatureFlag('PHAI_WEB_SEARCH')
    const errorTrackingModeEnabled = useFeatureFlag('PHAI_ERROR_TRACKING_MODE')
    const surveyModeEnabled = useFeatureFlag('PHAI_SURVEY_MODE')
    const flagsModeEnabled = useFeatureFlag('POSTHOG_AI_FLAGS_MODE')

    const hasExistingMessages = threadMessageCount > 0
    const modeOptions = useMemo(
        () =>
            getModeOptions({
                planModeEnabled,
                researchEnabled,
                webSearchEnabled,
                errorTrackingModeEnabled,
                flagsModeEnabled,
                surveyModeEnabled,
                hasExistingMessages,
            }),
        [
            planModeEnabled,
            researchEnabled,
            webSearchEnabled,
            errorTrackingModeEnabled,
            surveyModeEnabled,
            hasExistingMessages,
            flagsModeEnabled,
            surveyModeEnabled,
        ]
    )

    const handleChange = useCallback(
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

    return (
        <LemonSelect
            value={isDeepResearch ? 'research' : agentMode}
            onChange={handleChange}
            options={modeOptions}
            size="xxsmall"
            type="tertiary"
            disabledReason={
                isDeepResearch
                    ? "You're in research mode, start a new conversation to change mode"
                    : contextDisabledReason
            }
            tooltip={buildGeneralTooltip(
                'Select a mode to focus PostHog AI on a specific product or task. Each mode unlocks specialized capabilities, tools, and expertise.',
                getDefaultTools({ webSearchEnabled })
            )}
            dropdownPlacement="top-start"
            dropdownMatchSelectWidth={false}
            menu={{ className: 'min-w-48' }}
            className="flex-shrink-0 border [&>span]:text-secondary"
        />
    )
}
