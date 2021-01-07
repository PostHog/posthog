import React from 'react'
import { Button, Card, Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'
import { DownOutlined } from '@ant-design/icons'
import { CloseButton } from 'lib/components/CloseButton'
import { EventPropertyFilter } from 'scenes/sessions/EventPropertyFilter'
import { EventTypePropertyFilter } from '~/types'

interface Props {
    i?: boolean
}

const SECTIONS: Record<string, { label: string; description: string }> = {
    action_type: {
        label: 'Action filters',
        description: 'Find sessions where user has done a given action',
    },
    event_type: {
        label: 'Event filters',
        description: 'Find sessions where user has done a given event',
    },
    cohort: {
        label: 'Cohort filters',
        description: 'Find sessions by users in the following cohorts',
    },
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
                            <Row style={{ width: '100%' }}>
                                <Col span={6}>
                                    <Button
                                        onClick={() => openFilterSelect(selector)}
                                        className="full-width"
                                        style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                        }}
                                    >
                                        {item.label}
                                        <DownOutlined style={{ fontSize: 12, color: '#bfbfbf' }} />
                                    </Button>
                                </Col>
                                {['event_type', 'action_type'].includes(item.type) && (
                                    <EventPropertyFilter filter={item as EventTypePropertyFilter} selector={selector} />
                                )}
                            </Row>
                            <CloseButton onClick={() => removeFilter(selector)} style={{ marginLeft: 8 }} />
                        </div>
                    ))}
                </div>
            ))}

            <Button onClick={() => openFilterSelect('new')}>+</Button>
            <Button className="float-right">close</Button>
        </Card>
    )
}
