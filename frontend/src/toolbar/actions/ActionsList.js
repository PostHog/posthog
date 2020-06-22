import React from 'react'
import { useActions, useValues } from 'kea'
import { actionsLogic } from '~/toolbar/elements/actionsLogic'
import { Button, Divider, Spin } from 'antd'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { SearchOutlined } from '@ant-design/icons'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ExportOutlined } from '@ant-design/icons'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export function ActionsList() {
    const { actionsForCurrentUrl, allActions, allActionsLoading } = useValues(actionsLogic)
    const { selectAction } = useActions(actionsTabLogic)
    const { disableInspect, enableInspect } = useActions(elementsLogic)
    const { inspectEnabled } = useValues(elementsLogic)

    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-block">
            <a
                href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}actions`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ float: 'right', marginTop: -3 }}
            >
                All Actions <ExportOutlined />
            </a>

            <h1 className="section-title">Actions</h1>
            {allActions.length === 0 && allActionsLoading ? (
                <Spin />
            ) : (
                <>
                    <div>{allActions.length} actions total</div>
                    <div>{actionsForCurrentUrl.length} actions in use on the current url</div>

                    <ol>
                        {actionsForCurrentUrl.map(action => (
                            <li key={action.id} onClick={() => selectAction(action.id)} style={{ cursor: 'pointer' }}>
                                {action.name || 'Untitled'}
                            </li>
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
