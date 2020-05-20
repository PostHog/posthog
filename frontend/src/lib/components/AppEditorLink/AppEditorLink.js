import React, { useState } from 'react'
import { useValues } from 'kea'

import { EditAppUrls } from './EditAppUrls'
import { appEditorUrl } from './utils'
import { userLogic } from '../../../scenes/userLogic'
import { Modal } from 'antd'

export function AppEditorLink({ actionId, style, className, children }) {
    const [modalOpen, setModalOpen] = useState(false)
    const { user } = useValues(userLogic)
    const appUrls = user.team.app_urls

    return (
        <>
            <a
                href={appEditorUrl(actionId, appUrls && appUrls[0])}
                style={style}
                className={className}
                onClick={e => {
                    e.preventDefault()
                    setModalOpen(true)
                }}
            >
                {children}
            </a>
            <Modal
                visible={modalOpen}
                title={
                    actionId
                        ? 'Where do you want to edit this action?'
                        : 'On which domain do you want to create an action?'
                }
                onDismiss={() => setModalOpen(false)}
            >
                <EditAppUrls actionId={actionId} allowNavigation={true} dismissModal={() => setModalOpen(false)} />
            </Modal>
        </>
    )
}
