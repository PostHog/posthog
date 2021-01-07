import React, { Fragment } from 'react'
import { Button, Card, Col, Divider, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'
import { DownOutlined } from '@ant-design/icons'
import { CloseButton } from 'lib/components/CloseButton'

interface Props {
    i?: boolean
}

const SECTIONS: Record<string, { label: string, description: string }> = {
    action_type: {
        label: 'Action filters',
        description: 'Find sessions that match the following values'
    }
}

export function SessionsEditFiltersPanel({}: Props): JSX.Element {
    const { displayedFilters } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, removeFilter } = useActions(sessionsFiltersLogic)

    return (
        <Card>
            {/* <pre>{JSON.stringify(displayedFilters, null, 2)}</pre> */}

            {Object.entries(displayedFilters).map(([key, filters]) => (
                <div key={key}>
                    <div className="sessions-filter-title">
                        <strong>{SECTIONS[key].label}</strong> · {SECTIONS[key].description}
                    </div>
                    {filters.map(({ item, selector }) => (
                        <div className="sessions-filter-row" key={selector}>
                            <Button onClick={() => openFilterSelect(selector)}>
                                Has done {item.label}
                                <DownOutlined style={{ fontSize: 12, color: '#bfbfbf' }} />
                            </Button>
                            <CloseButton onClick={() => removeFilter(selector)} />
                        </div>
                    ))}
                </div>
            ))}

            <Button onClick={() => openFilterSelect('new')}>+</Button>
            <Button>collapse</Button>
        </Card>
    )
}
