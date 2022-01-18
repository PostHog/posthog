import React from 'react'
import { Select } from 'antd'
import { useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

interface EventNameInterface {
    value: string
    onChange: (value: string) => void
    isActionStep?: boolean
}

export function EventName({ value, onChange, isActionStep = false }: EventNameInterface): JSX.Element {
    const { eventNamesGrouped } = useValues(eventDefinitionsModel)

    return (
        <span>
            <Select
                showSearch
                allowClear
                style={{ width: '100%', maxWidth: '24rem' }}
                onChange={onChange}
                filterOption={(input, option) => option?.value?.toLowerCase().indexOf(input.toLowerCase()) >= 0}
                disabled={isActionStep && eventNamesGrouped[0].options.length === 0}
                value={value || undefined}
                placeholder="Choose an event"
                data-attr="event-name-box"
            >
                {eventNamesGrouped.map((typeGroup) => {
                    if (typeGroup.options.length > 0) {
                        return (
                            <Select.OptGroup key={typeGroup.label} label={typeGroup.label}>
                                {typeGroup.options.map((item, index) => (
                                    <Select.Option key={item.value} value={item.value} data-attr={'prop-val-' + index}>
                                        <PropertyKeyInfo value={item.label ?? item.value} />
                                    </Select.Option>
                                ))}
                            </Select.OptGroup>
                        )
                    }
                })}
            </Select>
            {isActionStep && (
                <>
                    <br />

                    <small>
                        {eventNamesGrouped[0].options.length === 0 && "You haven't sent any custom events."}{' '}
                        <a href="https://posthog.com/docs/libraries" target="_blank" rel="noopener noreferrer">
                            See documentation
                        </a>{' '}
                        on how to send custom events in lots of languages.
                    </small>
                </>
            )}
        </span>
    )
}
