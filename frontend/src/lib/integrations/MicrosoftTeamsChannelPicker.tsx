import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { microsoftTeamsIntegrationLogic } from './microsoftTeamsIntegrationLogic'

export type MicrosoftTeamsChannelPickerProps = {
    integration: IntegrationType
    teamId: string
    value?: string
    onChange?: (value: string | null) => void
}

export function MicrosoftTeamsChannelPicker({
    integration,
    teamId,
    value,
    onChange,
}: MicrosoftTeamsChannelPickerProps): JSX.Element {
    const logic = microsoftTeamsIntegrationLogic({ id: integration.id })
    const { microsoftTeamsChannels, microsoftTeamsChannelsLoading } = useValues(logic)
    const { loadMicrosoftTeamsChannels } = useActions(logic)

    useEffect(() => {
        loadMicrosoftTeamsChannels(teamId)
    }, [loadMicrosoftTeamsChannels, teamId])

    const options = useMemo(
        () =>
            microsoftTeamsChannels
                ? microsoftTeamsChannels.map((channel) => ({ key: channel.id, label: channel.name }))
                : value
                  ? [{ key: value, label: value }]
                  : [],
        [microsoftTeamsChannels, value]
    )

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-microsoft-teams-channel"
            placeholder="Select a channel..."
            options={options}
            loading={microsoftTeamsChannelsLoading}
        />
    )
}
