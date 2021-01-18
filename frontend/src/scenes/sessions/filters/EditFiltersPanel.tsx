import React from 'react'
import { Button, Card, Col, Divider, Row, Space } from 'antd'
import { useActions, useValues } from 'kea'
import { DownOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons'
import { CloseButton } from 'lib/components/CloseButton'
import { EventTypePropertyFilter, PersonPropertyFilter, RecordingPropertyFilter } from '~/types'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { EventPropertyFilter } from 'scenes/sessions/filters/EventPropertyFilter'
import { PersonFilter } from 'scenes/sessions/filters/UserFilter'
import { DurationFilter } from 'scenes/sessions/filters/DurationFilter'
import { SessionsFilterBox } from 'scenes/sessions/filters/SessionsFilterBox'
import { AddFilterButton } from 'scenes/sessions/filters/AddFilterButton'

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

export function EditFiltersPanel({ onSubmit }: Props): JSX.Element | null {
    const { activeFilter, displayedFilterCount, displayedFilters } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, removeFilter } = useActions(sessionsFiltersLogic)

    if (displayedFilterCount === 0) {
        return null
    }

    return (
        <Card>
            {Object.entries(displayedFilters).map(([key, filters]) => (
                <div key={key}>
                    <div className="sessions-filter-title">
                        <h3>{SECTIONS[key].label}</h3>
                        <p className="text-muted">{SECTIONS[key].description}</p>
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
                                        <strong>{item.label}</strong>
                                        <DownOutlined style={{ fontSize: 12, color: '#bfbfbf' }} />
                                    </Button>
                                    <SessionsFilterBox selector={selector} />
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
                    <div className="sessions-filter-row">
                        <div className="full-width">
                            <AddFilterButton selector={`new-${key}`} />
                        </div>
                    </div>
                    <Divider />
                </div>
            ))}

            <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button disabled={!!activeFilter}>
                    <span>
                        <SaveOutlined /> Save filter
                    </span>
                </Button>
                <Button type="primary" onClick={onSubmit}>
                    <span>
                        <SearchOutlined /> Apply filters
                    </span>
                </Button>
            </Space>
        </Card>
    )
}
