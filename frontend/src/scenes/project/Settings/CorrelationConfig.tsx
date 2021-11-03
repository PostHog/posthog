import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const handleChange = (excludedProperties: string[]): void => {
        updateCurrentTeam({ correlation_config: { excluded_person_property_names: excludedProperties } })
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <h3>Excluded person properties:</h3>
                {currentTeam && (
                    <PersonPropertySelect
                        onChange={handleChange}
                        selectedProperties={currentTeam.correlation_config.excluded_person_property_names || []}
                    />
                )}
            </div>
        </div>
    )
}
