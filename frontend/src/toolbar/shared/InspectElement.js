import React from 'react'
import { Button, Checkbox } from 'antd'
import { SearchOutlined, AimOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { inspectElementLogic } from './inspectElementLogic'
import { ActionStep } from '~/toolbar/shared/ActionStep'

export function InspectElement() {
    const { stop, start, selectAllElements, selectClickTargets } = useActions(inspectElementLogic)
    const { selecting, element, selectingClickTargets, actionStep } = useValues(inspectElementLogic)

    return (
        <div className="toolbar-block">
            <div style={{ fontSize: 16, marginBottom: 10 }}>
                <SearchOutlined /> Select an element
            </div>
            <div>
                <Button type={selecting ? 'primary' : 'secondary'} onClick={selecting ? stop : start}>
                    <AimOutlined />
                </Button>
                <span style={{ marginLeft: 20, display: selecting ? 'inline-block' : 'none' }}>
                    <Checkbox
                        checked={selectingClickTargets}
                        onClick={selectingClickTargets ? selectAllElements : selectClickTargets}
                    >
                        {' '}
                        Only Clickable
                    </Checkbox>
                </span>
            </div>
            <div style={{ marginTop: 10 }}>
                {element ? (
                    <div style={{ marginTop: 10 }}>
                        <ActionStep actionStep={actionStep} />
                    </div>
                ) : null}
            </div>
        </div>
    )
}
