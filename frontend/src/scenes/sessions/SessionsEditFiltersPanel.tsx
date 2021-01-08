import React from 'react'
import { Button, Card, Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'
import { DownOutlined, PlusCircleOutlined } from '@ant-design/icons'
import { CloseButton } from 'lib/components/CloseButton'
import { EventPropertyFilter } from 'scenes/sessions/EventPropertyFilter'
import { EventTypePropertyFilter, PersonPropertyFilter } from '~/types'
import { PersonFilter } from 'scenes/sessions/UserFilter'

interface Props {
    onSubmit: () => void
}

const SECTIONS: Record<string, { label: string; description: string }> = {
    person: {
        label: 'User property filters',
        description: 'Find sessions where user properties match the following',
    },
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

export function SessionsEditFiltersPanel({ onSubmit }: Props): JSX.Element {
    const { displayedFilters } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, removeFilter } = useActions(sessionsFiltersLogic)

    return (
        <Card>
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
                                {item.type === 'person' && (
                                    <PersonFilter filter={item as PersonPropertyFilter} selector={selector} />
                                )}
                            </Row>
                            <CloseButton onClick={() => removeFilter(selector)} style={{ marginLeft: 8 }} />
                        </div>
                    ))}
                </div>
            ))}

            <div style={{ marginBottom: 8 }}>
                <Button onClick={() => openFilterSelect('new')}>
                    <PlusCircleOutlined />
                </Button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center' }}>
                <Button type="primary" onClick={onSubmit}>
                    Apply filters
                </Button>
            </div>
        </Card>
    )
}
