import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import PlusCircleOutlined from '@ant-design/icons/lib/icons/PlusCircleOutlined'
import { Button } from 'antd'

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
                {currentTeam && (
                    <>
                        <h3>Excluded person properties:</h3>
                        <PersonPropertySelect
                            onChange={handlePersonPropertiesChange}
                            selectedProperties={currentTeam.correlation_config.excluded_person_property_names || []}
                        />

                        <h3>Excluded events:</h3>
                        <EventSelect
                            onChange={handleEventsChange}
                            selectedEvents={currentTeam.correlation_config.excluded_events || []}
                            addElement={
                                <Button type="link" className="new-prop-filter" icon={<PlusCircleOutlined />}>
                                    Add exclusion
                                </Button>
                            }
                        />
                    </>
                )}
            </div>
        </div>
    )
}
