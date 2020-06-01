import React from 'react'
import { Button, Checkbox } from 'antd'
import {
    SearchOutlined,
    AimOutlined,
    FontSizeOutlined,
    LinkOutlined,
    FormOutlined,
    CodeOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { inspectElementLogic } from './inspectElementLogic'

function ActionAttribute({ attribute, value }) {
    const icon =
        attribute === 'text' ? (
            <FontSizeOutlined />
        ) : attribute === 'href' ? (
            <LinkOutlined />
        ) : attribute === 'selector' ? (
            <CodeOutlined />
        ) : (
            <FormOutlined />
        )

    const text =
        attribute === 'href' ? (
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
        ) : attribute === 'selector' ? (
            <span style={{ fontFamily: 'monospace' }}>{value}</span>
        ) : (
            value
        )

    return (
        <div key={attribute} style={{ marginBottom: 10, paddingLeft: 24, position: 'relative' }}>
            <div style={{ position: 'absolute', left: 2, top: 3, color: 'hsl(240, 14%, 50%)' }}>{icon}</div>
            <span>{text}</span>
        </div>
    )
}

export function InspectElement() {
    const { stop, start, selectAllElements, selectClickTargets } = useActions(inspectElementLogic)
    const { selecting, element, selectingClickTargets, actionStep } = useValues(inspectElementLogic)

    return (
        <div className="float-box">
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
                        Links Only
                    </Checkbox>
                </span>
            </div>
            <div style={{ marginTop: 10 }}>
                {element ? (
                    <div style={{ marginTop: 10 }}>
                        <div style={{ fontSize: 16, marginBottom: 10 }}>&lt;{actionStep.tag_name}&gt;</div>
                        {['text', 'name', 'href', 'selector'].map(attr =>
                            actionStep[attr] ? (
                                <ActionAttribute key={attr} attribute={attr} value={actionStep[attr]} />
                            ) : null
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    )
}
