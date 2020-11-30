import React from 'react'
import { Select } from 'antd'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function EventName({ value, onChange, isActionStep }) {
    const { eventNamesGrouped } = useValues(userLogic)

    return (
        <span>
            <Select
                showSearch
                allowClear
                style={{ width: '100%' }}
                onChange={onChange}
                filterOption={(input, option) =>
                    option.children && option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
                }
                disabled={isActionStep && eventNamesGrouped[0].options.length === 0}
                value={value}
                data-attr="event-name-box"
            >
                {eventNamesGrouped.map((typeGroup) => {
                    if (typeGroup.options.length > 0) {
                        return (
                            <Select.OptGroup key={typeGroup.label} label={typeGroup.label}>
                                {typeGroup.options.map((item, index) => (
                                    <Select.Option key={item.value} value={item.value} data-attr={'prop-val-' + index}>
                                        {item.label}
                                    </Select.Option>
                                ))}
                            </Select.OptGroup>
                        )
                    }
                })}
            </Select>
            <br />
            {isActionStep && (
                <small>
                    {eventNamesGrouped[0].options.length === 0 && "You haven't sent any custom events."}{' '}
                    <a href="https://posthog.com/docs/integrations" target="_blank" rel="noopener noreferrer">
                        See documentation
                    </a>{' '}
                    on how to send custom events in lots of languages.
                </small>
            )}
        </span>
    )
}
