import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { CustomChannelRule } from '~/queries/schema'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

export function ChannelType(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportCustomChannelTypeRulesUpdated } = useActions(eventUsageLogic)

    const savedCustomChannelTypeRules =
        currentTeam?.modifiers?.customChannelTypeRules ?? currentTeam?.default_modifiers?.customChannelTypeRules ?? null
    const [customChannelTypeRules, setCustomChannelTypeRules] = useState<string>(
        savedCustomChannelTypeRules ? JSON.stringify(savedCustomChannelTypeRules) : ''
    )

    const handleChange = (rules: string): void => {
        let parsed: CustomChannelRule[] = []
        try {
            parsed = JSON.parse(rules)
        } catch (e) {
            return
        }

        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, customChannelTypeRules: parsed } })
        reportCustomChannelTypeRulesUpdated(parsed.length)
    }

    return (
        <>
            <p>Set your custom channel type</p>
            <LemonInput
                value={customChannelTypeRules}
                onChange={setCustomChannelTypeRules}
                placeholder="Enter JSON array of custom channel type rules"
            />
            <div className="mt-4">
                <LemonButton type="primary" onClick={() => handleChange(customChannelTypeRules)}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
