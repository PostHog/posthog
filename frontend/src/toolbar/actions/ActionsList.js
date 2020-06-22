import React from 'react'
import { useValues } from 'kea'
import { actionsLogic } from '~/toolbar/elements/actionsLogic'
import { Spin } from 'antd'

export function ActionsList() {
    const { actionsForCurrentUrl, allActions, allActionsLoading } = useValues(actionsLogic)
    return (
        <div className="toolbar-block">
            <h1 className="section-title">Actions</h1>
            {allActions.length === 0 && allActionsLoading ? (
                <Spin />
            ) : (
                <>
                    <div>{allActions.length} actions</div>
                    <div>{actionsForCurrentUrl.length} actions for current url</div>
                </>
            )}
        </div>
    )
}
