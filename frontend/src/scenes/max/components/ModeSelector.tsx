import { useActions, useValues } from 'kea'

import { IconShuffle } from '@posthog/icons'
import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import { MODE_DEFINITIONS } from '../max-constants'
import { maxThreadLogic } from '../maxThreadLogic'

type ModeValue = AgentMode | 'deep_research' | null

const MODE_OPTIONS: LemonSelectOption<ModeValue>[] = [
    { value: null, label: 'Auto' },
    ...Object.entries(MODE_DEFINITIONS).map(([mode, definition]) => ({
        value: mode as AgentMode,
        label: definition.name.charAt(0).toUpperCase() + definition.name.slice(1),
    })),
    { value: 'deep_research', label: 'Deep research' },
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
            disabled={threadLoading}
            icon={<IconShuffle />}
            dropdownPlacement="top-start"
            dropdownMatchSelectWidth={false}
            className="rounded-full px-1 h-7 min-h-0 border border-primary"
        />
    )
}
