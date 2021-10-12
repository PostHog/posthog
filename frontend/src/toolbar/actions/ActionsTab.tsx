import './ActionsTab.scss'

import React from 'react'

import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'
import { ExportOutlined } from '@ant-design/icons'
import { urls } from 'scenes/urls'

export function ActionsTab(): JSX.Element {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-content">
            <div className="toolbar-block action-block-body">
                {selectedAction ? (
                    <EditAction />
                ) : (
                    <>
                        <ActionsList />
                        <div style={{ textAlign: 'right' }}>
                            <a href={`${apiURL}${urls.actions()}`} target="_blank" rel="noopener noreferrer">
                                View &amp; edit all actions <ExportOutlined />
                            </a>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
