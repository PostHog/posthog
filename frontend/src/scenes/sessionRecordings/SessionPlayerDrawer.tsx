import React from 'react'

import { Drawer } from 'lib/components/Drawer'
import { SessionsPlay } from 'scenes/sessions/SessionsPlay'
import { useActions } from 'kea'
import { ArrowTopLeftOutlined } from 'lib/components/icons'
import { sessionRecordingsTableLogic } from './sessionRecordingsLogic'

export function SessionPlayerDrawer({ isPersonPage = false }: { isPersonPage: boolean }): JSX.Element {
    const { closeSessionPlayer } = useActions(sessionRecordingsTableLogic)
    return (
        <Drawer destroyOnClose visible width="100%" onClose={closeSessionPlayer}>
            <>
                <a onClick={closeSessionPlayer}>
                    <ArrowTopLeftOutlined /> Back to {isPersonPage ? 'persons' : 'sessions'}
                </a>
                <SessionsPlay />
            </>
        </Drawer>
    )
}
