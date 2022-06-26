import React, { useState } from 'react'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { Modal, Button } from 'antd'
import { AuthorizedUrls } from 'scenes/toolbar-launch/AuthorizedUrls'
import { appEditorUrl } from 'scenes/toolbar-launch/authorizedUrlsLogic'

export function AppEditorLink({
    actionId,
    style,
    children,
}: {
    actionId?: number
    style?: React.CSSProperties
    children: React.ReactNode
}): JSX.Element {
    const [modalOpen, setModalOpen] = useState(false)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <Button
                href={appEditorUrl(currentTeam?.app_urls?.[0], actionId)}
                style={style}
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    setModalOpen(true)
                }}
            >
                {children}
            </Button>
            <Modal
                visible={modalOpen}
                title={
                    actionId
                        ? 'Choose the domain on which to edit this action'
                        : 'Choose the domain on which to create this action'
                }
                footer={<Button onClick={() => setModalOpen(false)}>Close</Button>}
                onCancel={() => setModalOpen(false)}
            >
                <AuthorizedUrls actionId={actionId} pageKey="app-editor-link" />
            </Modal>
        </>
    )
}
