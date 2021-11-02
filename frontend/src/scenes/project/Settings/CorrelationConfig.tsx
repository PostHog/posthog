import React from 'react'
import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { Select } from 'antd'
import { DEFAULT_EXCLUDED_PERSON_PROPERTIES } from 'scenes/funnels/funnelLogic'

export function CorrelationConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { personProperties } = useValues(personPropertiesModel)

    const handleChange = (excludedProperties: string[]): void => {
        updateCurrentTeam({ correlation_config: { excluded_person_property_names: excludedProperties } })
    }

    return (
        <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
                {currentTeam && (
                    <>
                        Excluded person properties:{' '}
                        <Select
                            mode="multiple"
                            allowClear
                            showSearch
                            value={
                                currentTeam.correlation_config?.excluded_person_property_names ||
                                DEFAULT_EXCLUDED_PERSON_PROPERTIES
                            }
                            onChange={handleChange}
                            style={{ width: 500 }}
                        >
                            {personProperties
                                .map(({ name }) => name)
                                .sort()
                                .map((name) => (
                                    <Select.Option key={name} value={name}>
                                        {name}
                                    </Select.Option>
                                ))}
                        </Select>
                    </>
                )}
            </div>
        </div>
    )
}
