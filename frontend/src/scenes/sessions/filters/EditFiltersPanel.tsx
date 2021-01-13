import React from 'react'
import { Button, Card, Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { DownOutlined, PlusCircleOutlined } from '@ant-design/icons'
import { CloseButton } from 'lib/components/CloseButton'
import { EventTypePropertyFilter, PersonPropertyFilter, RecordingPropertyFilter } from '~/types'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { EventPropertyFilter } from 'scenes/sessions/filters/EventPropertyFilter'
import { PersonFilter } from 'scenes/sessions/filters/UserFilter'
import { DurationFilter } from 'scenes/sessions/filters/DurationFilter'

interface Props {
    onSubmit: () => void
}

const SECTIONS: Record<string, { label: string; description: string }> = {
    recording: {
        label: 'Recording filters',
        description: 'Find sessions with recordings matching the following',
    },
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

export function EditFiltersPanel({ onSubmit }: Props): JSX.Element {
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
                                {item.type === 'recording' && item.key === 'duration' && (
                                    <DurationFilter filter={item as RecordingPropertyFilter} selector={selector} />
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
