import React from 'react'

import { Drawer } from 'lib/components/Drawer'
import { SessionsPlay } from 'scenes/sessions/SessionsPlay'
import { useActions } from 'kea'
import { ArrowTopLeftOutlined } from 'lib/components/icons'
import { sessionRecordingsTableLogic } from './sessionRecordingsLogic'

interface SessionPlayerDrawerProps {
    personIds?: string[]
    isPersonPage?: boolean
}

export function SessionPlayerDrawer({ personIds, isPersonPage = false }: SessionPlayerDrawerProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personIds })

    const { closeSessionPlayer } = useActions(sessionRecordingsTableLogicInstance)
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
