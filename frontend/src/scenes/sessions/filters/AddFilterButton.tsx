import React from 'react'
import { Button } from 'antd'
import { useActions } from 'kea'
import { DownOutlined, PlusOutlined } from '@ant-design/icons'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { SessionsFilterBox } from 'scenes/sessions/filters/SessionsFilterBox'

export function AddFilterButton({ selector }: { selector: string }): JSX.Element {
    const { openFilterSelect } = useActions(sessionsFiltersLogic)

    return (
        <>
            <Button onClick={() => openFilterSelect(selector)} className="add-session-filter">
                <span>
                    <PlusOutlined />
                    <span style={{ marginLeft: 8 }}>Add filter</span>
                </span>
                <DownOutlined style={{ fontSize: 12, color: 'var(--muted)' }} />
            </Button>
            <SessionsFilterBox selector={selector} />
        </>
    )
}
