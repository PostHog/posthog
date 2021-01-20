import React from 'react'
import { Button, Card, Divider, Space } from 'antd'
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
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'

interface Props {
    onSubmit: () => void
}

const SECTIONS: Record<string, { label: string; description: JSX.Element }> = {
    recording: {
        label: 'Recording filters',
        description: (
            <>
                Find sessions <b>with recordings</b> matching the following
            </>
        ),
    },
    person: {
        label: 'User property filters',
        description: (
            <>
                Find sessions where user properties match <b>all</b> of the following
            </>
        ),
    },
    action_type: {
        label: 'Action filters',
        description: (
            <>
                Find sessions where a given <b>action</b> has been triggered
            </>
        ),
    },
    event_type: {
        label: 'Event filters',
        description: (
            <>
                Find sessions where a given <b>event</b> has been triggered
            </>
        ),
    },
    cohort: {
        label: 'Cohort filters',
        description: (
            <>
                Find sessions by <b>users in</b> the following cohorts
            </>
        ),
    },
}

export function EditFiltersPanel({ onSubmit }: Props): JSX.Element | null {
    const { activeFilter, displayedFilterCount, displayedFilters } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, openEditFilter, removeFilter } = useActions(sessionsFiltersLogic)
    const { filtersDirty } = useValues(sessionsTableLogic)

    if (displayedFilterCount === 0) {
        return null
    }

    const andTag = (visible: boolean): JSX.Element => (
        <span className="stateful-badge and" style={{ visibility: visible ? 'initial' : 'hidden', marginLeft: 16 }}>
            AND
        </span>
    )

    return (
        <Card>
            {Object.entries(displayedFilters).map(([key, filters]) => (
                <div key={key}>
                    <div className="sessions-filter-title">
                        <h3>{SECTIONS[key].label}</h3>
                        <p className="text-muted">{SECTIONS[key].description}</p>
                    </div>
                    {filters.map(({ item, selector }, index) => (
                        <div className="sessions-filter-row" key={selector}>
                            <div className="sessions-filter-row-filters">
                                <div>
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
                                </div>
                                {['event_type', 'action_type'].includes(item.type) && (
                                    <EventPropertyFilter filter={item as EventTypePropertyFilter} selector={selector} />
                                )}
                                {item.type === 'person' && (
                                    <PersonFilter filter={item as PersonPropertyFilter} selector={selector} />
                                )}
                                {item.type === 'recording' && item.key === 'duration' && (
                                    <DurationFilter filter={item as RecordingPropertyFilter} selector={selector} />
                                )}
                            </div>
                            {filters.length > 1 && andTag(index < filters.length - 1)}
                            <CloseButton onClick={() => removeFilter(selector)} style={{ marginLeft: 8 }} />
                        </div>
                    ))}
                    <div className="sessions-filter-row">
                        <div className="sessions-filter-row-filters">
                            <AddFilterButton selector={`new-${key}`} />
                        </div>
                        {filters.length > 1 && andTag(false)}
                        <CloseButton style={{ marginLeft: 8, visibility: 'hidden' }} />
                    </div>
                    <Divider />
                </div>
            ))}

            <Space style={{ display: 'flex', justifyContent: 'flex-end' }}>
                {filtersDirty && <div className="text-warning">There are unapplied filters.</div>}
                <Button disabled={!!activeFilter} onClick={() => openEditFilter({ id: null })}>
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
