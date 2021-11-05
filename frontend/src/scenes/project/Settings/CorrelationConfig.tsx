import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { Divider, Select, Tag } from 'antd'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import PlusCircleOutlined from '@ant-design/icons/lib/icons/PlusCircleOutlined'
import { Button } from 'antd'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, funnelCorrelationConfig } = useValues(teamLogic)

    const handleChange = (
        excludedProperties?: string[],
        excludedEvents?: string[],
        excludedEventProperties?: string[]
    ): void => {
        if (currentTeam) {
            const updatedConfig = { ...funnelCorrelationConfig }
            if (excludedProperties?.length) {
                updatedConfig.excluded_person_property_names = excludedProperties
            }
            if (excludedEventProperties?.length) {
                updatedConfig.excluded_event_property_names = excludedEventProperties
            }
            if (excludedEvents?.length) {
                updatedConfig.excluded_event_names = excludedEvents
            }
            if (updatedConfig) {
                updateCurrentTeam({ correlation_config: updatedConfig })
            }
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
                Correlation analysis exclusions
            </h2>
            <p>
                Correlation analysis can automatically surface relevant signals for conversion, and help you understand
                why your users dropped off and what makes them convert. Some events are excluded by default because they
                are non-meaningful to the analysis.
            </p>
            <Divider />
            {currentTeam && (
                <>
                    <h3>Excluded person properties</h3>
                    <PersonPropertySelect
                        onChange={(properties) => handleChange(properties)}
                        selectedProperties={currentTeam.correlation_config.excluded_person_property_names || []}
                    />
                    <h3>Excluded events</h3>
                    <EventSelect
                        onChange={(excludedEvents) => handleChange(undefined, excludedEvents)}
                        selectedEvents={currentTeam.correlation_config.excluded_event_names || []}
                        addElement={
                            <Button type="link" className="new-prop-filter" icon={<PlusCircleOutlined />}>
                                Add exclusion
                            </Button>
                        }
                    />
                    <h3>Excluded event Properties</h3>
                    <div style={{ marginBottom: 8 }}>
                        {currentTeam && (
                            <Select
                                mode="tags"
                                style={{ width: '50%', marginTop: 5 }}
                                tagRender={tagRender}
                                onChange={(properties) => handleChange(undefined, undefined, properties)}
                                value={currentTeam.correlation_config.excluded_event_property_names || []}
                                tokenSeparators={[',']}
                            />
                        )}
                    </div>
                </>
            )}
        </>
    )
}
