import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { PersonPropertySelect } from 'lib/components/PersonPropertySelect/PersonPropertySelect'
import { Divider, Select, SelectProps, Tag } from 'antd'
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
            if (excludedProperties !== undefined) {
                updatedConfig.excluded_person_property_names = excludedProperties
            }
            if (excludedEventProperties !== undefined) {
                updatedConfig.excluded_event_property_names = excludedEventProperties
            }
            if (excludedEvents !== undefined) {
                updatedConfig.excluded_event_names = excludedEvents
            }
            if (updatedConfig && JSON.stringify(updatedConfig) !== JSON.stringify(funnelCorrelationConfig)) {
                updateCurrentTeam({ correlation_config: updatedConfig })
            }
        }
    }

    const tagRender: SelectProps<any>['tagRender'] = (props) => {
        const { label, onClose } = props
        return (
            <Tag
                closable={true}
                onClose={onClose}
                style={{
                    margin: '0.25rem',
                    padding: '0.25rem 0.5em',
                    background: '#D9D9D9',
                    border: '1px solid #D9D9D9',
                    borderRadius: '40px',
                }}
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
                    <p> Choose event properties to exclude across all events.</p>
                    <div style={{ marginBottom: 8 }}>
                        <Select
                            mode="tags"
                            style={{ width: '100%' }}
                            allowClear
                            tagRender={tagRender}
                            onChange={(properties) => handleChange(undefined, undefined, properties)}
                            value={currentTeam.correlation_config.excluded_event_property_names || []}
                            tokenSeparators={[',']}
                        />
                    </div>
                </>
            )}
        </>
    )
}
