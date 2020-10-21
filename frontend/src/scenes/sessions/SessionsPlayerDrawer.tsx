import React from 'react'
import { Button, Drawer } from 'antd'
import { useActions, useValues } from 'kea'
import { Loading } from 'lib/utils'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import SessionsPlayer from 'scenes/sessions/SessionsPlayer'

export default function SessionsPlayerDrawer(): JSX.Element {
    const { sessionPlayerData, sessionPlayerDataLoading, sessionRecordingNavigation: nav } = useValues(
        sessionsTableLogic
    )
    const { loadSessionPlayer, closeSessionPlayer } = useActions(sessionsTableLogic)

    return (
        <Drawer
            title="Session recording"
            width={1000}
            onClose={closeSessionPlayer}
            destroyOnClose={true}
            visible={true}
            footer={
                <>
                    {nav.prev && (
                        <Button style={{ marginRight: 12 }} onClick={() => loadSessionPlayer(nav.prev)}>
                            Previous
                        </Button>
                    )}
                    {nav.next && <Button onClick={() => loadSessionPlayer(nav.next)}>Next</Button>}
                </>
            }
        >
            {sessionPlayerDataLoading ? <Loading /> : <SessionsPlayer events={sessionPlayerData} />}
        </Drawer>
    )
}
