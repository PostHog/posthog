import { useActions, useValues } from 'kea'

import { IconWrench } from '@posthog/icons'
import { LemonSelect, LemonSelectSection, LemonTag } from '@posthog/lemon-ui'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import {
    MODE_DEFINITIONS,
    SPECIAL_MODES,
    SpecialMode,
    ToolDefinition,
    getDefaultTools,
    getToolsForMode,
} from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

type ModeValue = AgentMode | SpecialMode | null

function buildModeTooltip(description: string, tools: ToolDefinition[]): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
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

const MODE_OPTIONS: LemonSelectSection<ModeValue>[] = [
    {
        options: [
            {
                value: null,
                label: SPECIAL_MODES.auto.name,
                icon: SPECIAL_MODES.auto.icon,
                tooltip: buildModeTooltip(SPECIAL_MODES.auto.description, getDefaultTools()),
            },
            {
                value: 'deep_research',
                label: SPECIAL_MODES.deep_research.name,
                icon: SPECIAL_MODES.deep_research.icon,
                tooltip: SPECIAL_MODES.deep_research.description,
            },
        ],
    },
    {
        options: Object.entries(MODE_DEFINITIONS).map(([mode, def]) => ({
            value: mode as AgentMode,
            label: def.name,
            icon: def.icon,
            tooltip: buildModeTooltip(def.description, getToolsForMode(mode as AgentMode)),
        })),
    },
]

export function ModeSelector(): JSX.Element {
    const { agentMode, threadLoading, deepResearchMode } = useValues(maxThreadLogic)
    const { setAgentMode, setDeepResearchMode } = useActions(maxThreadLogic)

    const currentValue: ModeValue = deepResearchMode ? 'deep_research' : agentMode

    const handleChange = (value: ModeValue): void => {
        if (value === 'deep_research') {
            setDeepResearchMode(true)
            setAgentMode(null)
        } else {
            setDeepResearchMode(false)
            setAgentMode(value)
        }
    }

    return (
        <LemonSelect
            value={currentValue}
            onChange={handleChange}
            options={MODE_OPTIONS}
            size="xsmall"
            type="tertiary"
            tooltip="Select the agent mode. The agent modes inject specific capabilities and tools to best suit your request."
            disabledReason={threadLoading ? 'Loading...' : undefined}
            dropdownPlacement="top-start"
            dropdownMatchSelectWidth={false}
            className="rounded-full px-1 h-7 min-h-0 border border-primary"
        />
    )
}
