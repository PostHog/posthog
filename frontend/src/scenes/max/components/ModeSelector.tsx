import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useMemo } from 'react'

import { IconWrench } from '@posthog/icons'
import { LemonSelect, LemonSelectSection, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationType } from '~/types'

import {
    MODE_DEFINITIONS,
    ModeDefinition,
    SPECIAL_MODES,
    SpecialMode,
    ToolDefinition,
    getDefaultTools,
} from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

type ModeValue = AgentMode | SpecialMode | null

// One fixed tooltip on the trigger describes every mode. Per-row tooltips are
// avoided on purpose: they mount a differently sized popover at a different
// anchor on each hover, which makes the menu flicker and the rows shift.
function buildGeneralTooltip(
    description: string,
    defaultTools: ToolDefinition[],
    modes: ModeDefinition[]
): JSX.Element {
    return (
        <div className="max-w-sm max-h-[calc(100vh_-_var(--spacing)*5)] overflow-y-auto show-scrollbar-on-hover flex flex-col gap-1.5">
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
            {modes.length > 0 && (
                <div>
                    <div className="font-semibold mb-0.5">Modes:</div>
                    <ul className="space-y-1 text-sm">
                        {modes.map((mode) => (
                            <li key={mode.name}>
                                <em>{mode.name}:</em> {mode.description}
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
    featureFlags: Record<string, boolean | string>
    hasExistingMessages: boolean
}

function getModeOptions({
    planModeEnabled,
    researchEnabled,
    featureFlags,
    hasExistingMessages,
}: GetModeOptionsParams): LemonSelectSection<ModeValue>[] {
    const specialOptions = [
        {
            value: null as ModeValue,
            label: SPECIAL_MODES.auto.name as string | JSX.Element,
            icon: SPECIAL_MODES.auto.icon,
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
                label:
                    def.beta || def.alpha ? (
                        <span className="flex items-center gap-1">
                            {def.name}
                            {def.beta && (
                                <LemonTag size="small" type="warning">
                                    BETA
                                </LemonTag>
                            )}
                            {def.alpha && (
                                <LemonTag size="small" type="danger">
                                    ALPHA
                                </LemonTag>
                            )}
                        </span>
                    ) : (
                        def.name
                    ),
                icon: def.icon,
            })),
        },
    ]
}

// The modes shown in the menu, in menu order, so the trigger tooltip describes exactly what a user can pick.
function getVisibleModes({
    planModeEnabled,
    researchEnabled,
    featureFlags,
    hasExistingMessages,
}: GetModeOptionsParams): ModeDefinition[] {
    const modes: ModeDefinition[] = [SPECIAL_MODES.auto]
    if (planModeEnabled) {
        modes.push(SPECIAL_MODES.plan)
    }
    if (researchEnabled && !hasExistingMessages) {
        modes.push(SPECIAL_MODES.research)
    }
    for (const def of Object.values(MODE_DEFINITIONS)) {
        if (def.flag && !featureFlags[FEATURE_FLAGS[def.flag]]) {
            continue
        }
        modes.push(def)
    }
    return modes
}

export function ModeSelector(): JSX.Element | null {
    const { agentMode, contextDisabledReason, conversation, threadMessageCount } = useValues(maxThreadLogic)
    const { setAgentMode } = useActions(maxThreadLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const researchEnabled = useFeatureFlag('MAX_DEEP_RESEARCH')
    const planModeEnabled = useFeatureFlag('PHAI_PLAN_MODE')

    const hasExistingMessages = threadMessageCount > 0
    const modeOptions = useMemo(
        () =>
            getModeOptions({
                planModeEnabled,
                researchEnabled,
                featureFlags,
                hasExistingMessages,
            }),
        [planModeEnabled, researchEnabled, featureFlags, hasExistingMessages]
    )
    const visibleModes = useMemo(
        () =>
            getVisibleModes({
                planModeEnabled,
                researchEnabled,
                featureFlags,
                hasExistingMessages,
            }),
        [planModeEnabled, researchEnabled, featureFlags, hasExistingMessages]
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
                getDefaultTools(),
                visibleModes
            )}
            dropdownPlacement="top-start"
            dropdownMatchSelectWidth={false}
            menu={{ className: 'min-w-48' }}
            className="flex-shrink-0 border [&>span]:text-secondary"
        />
    )
}
