import React from 'react'
import { DownOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

export function SearchAllBox(): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <div className="mb-05 full-width">
            <Button
                style={{ textAlign: 'left' }}
                data-attr="sessions-filter-open"
                onClick={() => (openFilter ? closeFilterSelect() : openFilterSelect('new'))}
            >
                <span className="text-muted">
                    Filter by user, action, or event properties
                    <DownOutlined
                        style={{
                            paddingLeft: '0.6em',
                            fontSize: '90%',
                            opacity: 0.5,
                        }}
                    />
                </span>
            </Button>
        </div>
    )
}
