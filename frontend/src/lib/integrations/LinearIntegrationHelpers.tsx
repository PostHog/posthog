import { LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IntegrationType } from '~/types'

import { linearIntegrationLogic } from './linearIntegrationLogic'

export type LinearTeamPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
}

export function LinearTeamPicker({ onChange, value, integration, disabled }: LinearTeamPickerProps): JSX.Element {
    const logic = linearIntegrationLogic({ id: integration.id })
    const { linearTeams, linearTeamsLoading } = useValues(logic)
    const { loadAllLinearTeams } = useActions(logic)

    const linearTeamOptions = useMemo(
        () =>
            linearTeams
                ? linearTeams.map((x) => ({
                      key: x.id,
                      label: x.name,
                  }))
                : [],
        [linearTeams]
    )

    useEffect(() => {
        if (!disabled) {
            loadAllLinearTeams()
        }
    }, [loadAllLinearTeams, disabled])

    return (
        <>
            <LemonInputSelect
                onChange={(val) => {
                    onChange?.(val[0] ?? null)
                }}
                value={value ? [value] : []}
                onFocus={() => !linearTeams.length && !linearTeamsLoading && loadAllLinearTeams()}
                disabled={disabled}
                mode="single"
                data-attr="select-linear-team"
                placeholder="Select a team..."
                options={linearTeamOptions}
                loading={linearTeamsLoading}
            />
        </>
    )
}
