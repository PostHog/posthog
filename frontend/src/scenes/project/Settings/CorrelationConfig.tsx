import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const handlePersonPropertiesChange = (excludedProperties: string[]): void => {
        if (currentTeam) {
            updateCurrentTeam({
                correlation_config: {
                    ...currentTeam.correlation_config,
                    excluded_person_property_names: excludedProperties,
                },
            })
        }
    }

    const handleEventsChange = (excludedEvents: string[]): void => {
        if (currentTeam) {
            updateCurrentTeam({
                correlation_config: {
                    ...currentTeam.correlation_config,
                    excluded_events: excludedEvents,
                },
            })
        }
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                <h3>Excluded person properties:</h3>
                {currentTeam && (
                    <>
                        <PersonPropertySelect
                            onChange={handlePersonPropertiesChange}
                            selectedProperties={currentTeam.correlation_config.excluded_person_property_names || []}
                        />

                        <EventSelect
                            onChange={handleEventsChange}
                            selectedEvents={currentTeam.correlation_config.excluded_events || []}
                        />
                    </>
                )}
            </div>
        </div>
    )
}
