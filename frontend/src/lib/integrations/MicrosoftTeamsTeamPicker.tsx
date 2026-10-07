import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { microsoftTeamsIntegrationLogic } from './microsoftTeamsIntegrationLogic'

export type MicrosoftTeamsTeamPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function MicrosoftTeamsTeamPicker({ integration, value, onChange }: MicrosoftTeamsTeamPickerProps): JSX.Element {
    const logic = microsoftTeamsIntegrationLogic({ id: integration.id })
    const { microsoftTeamsTeams, microsoftTeamsTeamsLoading } = useValues(logic)
    const { loadMicrosoftTeamsTeams } = useActions(logic)

    useEffect(() => {
        loadMicrosoftTeamsTeams()
    }, [loadMicrosoftTeamsTeams])

    const options = useMemo(
        () =>
            microsoftTeamsTeams
                ? microsoftTeamsTeams.map((team) => ({ key: team.id, label: team.name }))
                : value
                  ? [{ key: value, label: value }]
                  : [],
        [microsoftTeamsTeams, value]
    )

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-microsoft-teams-team"
            placeholder="Select a team..."
            options={options}
            loading={microsoftTeamsTeamsLoading}
        />
    )
}
