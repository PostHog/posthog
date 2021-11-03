import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { Divider, Select, Tag } from 'antd'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, funnelCorrelationConfig } = useValues(teamLogic)

    const handleChange = (excludedProperties?: string[], excludedEventProperties?: string[]): void => {
        const updatedConfig = { ...funnelCorrelationConfig }
        if (excludedProperties?.length) {
            updatedConfig.excluded_person_property_names = excludedProperties
        }
        if (excludedEventProperties?.length) {
            updatedConfig.excluded_event_property_names = excludedEventProperties
        }
        if (updatedConfig) {
            updateCurrentTeam({ correlation_config: updatedConfig })
        }
    }

    function tagRender(props: any): JSX.Element {
        // TODO: find antd default type for props
        const { label, onClose } = props
        return (
            <Tag
                closable={true}
                onClose={onClose}
                // TODO: style properly
                style={{ marginRight: 3 }}
            >
                {label}
            </Tag>
        )
    }

    return (
        <>
            <h2 className="subtitle" id="internal-users-filtering">
                Filter Out Correlation Person Property Noise
            </h2>
            <div style={{ marginBottom: 16 }}>
                <div style={{ marginBottom: 8 }}>
                    {currentTeam && (
                        <PersonPropertySelect
                            onChange={(properties) => handleChange(properties, undefined)}
                            selectedProperties={currentTeam.correlation_config.excluded_person_property_names || []}
                        />
                    )}
                </div>
                <Divider />
                <h2>Filter out Event Properties</h2>
                <div style={{ marginBottom: 8 }}>
                    {currentTeam && (
                        <Select
                            mode="tags"
                            style={{ width: '50%', marginTop: 5 }}
                            tagRender={tagRender}
                            onChange={(properties) => handleChange(undefined, properties)}
                            value={currentTeam.correlation_config.excluded_event_property_names || []}
                            tokenSeparators={[',']}
                        />
                    )}
                </div>
            </div>
        </>
    )
}
