import React, { Component } from 'react'
import api from '../../lib/api'
import Select from 'react-select'
import PropTypes from 'prop-types'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function EventName({ value, onChange }) {
    const { eventNamesGrouped } = useValues(userLogic)
    return (
        <span>
            <Select
                options={eventNamesGrouped}
                isSearchable={true}
                isClearable={true}
                onChange={onChange}
                disabled={eventNamesGrouped[0].options.length === 0}
                value={value ? { label: value, value } : null}
            />
            <br />
            {eventNamesGrouped[0].options.length === 0 && "You haven't sent any custom events."}{' '}
            <a href="https://docs.posthog.com/#/integrations" target="_blank">
                See documentation
            </a>{' '}
            on how to send custom events in lots of languages.
        </span>
    )
}
