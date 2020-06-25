import './ActionsTab.scss'

import React from 'react'

import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'
import { ExportOutlined } from '@ant-design/icons'

export function ActionsTab({ className }) {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className={`toolbar-content ${className || ''}`}>
            <div className="toolbar-block">
                {selectedAction ? (
                    <EditAction />
                ) : (
                    <>
                        <ActionsList />
                        <div style={{ textAlign: 'right' }}>
                            <a
                                href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}actions`}
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                View & Edit All Actions <ExportOutlined />
                            </a>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}
