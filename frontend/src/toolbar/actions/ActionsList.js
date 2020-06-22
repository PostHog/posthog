import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/elements/actionsLogic'
import { Button, Divider, Spin } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { SearchOutlined } from '@ant-design/icons'

export function ActionsList() {
    const { actionsForCurrentUrl, allActions, allActionsLoading } = useValues(actionsLogic)
    const { disableInspect, enableInspect } = useActions(elementsLogic)
    const { inspectEnabled } = useValues(elementsLogic)

    return (
        <div className="toolbar-block">
            <h1 className="section-title">Actions</h1>
            {allActions.length === 0 && allActionsLoading ? (
                <Spin />
            ) : (
                <>
                    <div>{allActions.length} actions</div>
                    <div>{actionsForCurrentUrl.length} actions for current url</div>

                    <ol>
                        {actionsForCurrentUrl.map(action => (
                            <li key={action.id}>{action.name || 'Untitled'}</li>
                        ))}
                    </ol>
                </>
            )}
            <Divider />
            <h1 className="section-title">New Action</h1>
            <p>Select an element to add an action</p>
            <Button
                type={inspectEnabled ? 'primary' : 'secondary'}
                onClick={inspectEnabled ? disableInspect : enableInspect}
            >
                <SearchOutlined /> Select an element
            </Button>
        </div>
    )
}
