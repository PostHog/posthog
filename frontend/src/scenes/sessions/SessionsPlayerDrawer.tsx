import React from 'react'
import { Button, Drawer } from 'antd'
import { useActions, useValues } from 'kea'
import { Loading } from 'lib/utils'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import SessionsPlayer from 'scenes/sessions/SessionsPlayer'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Player } from 'posthog-react-rrweb-player'

import 'posthog-react-rrweb-player/dist/index.css'

export default function SessionsPlayerDrawer(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const { sessionPlayerData, sessionPlayerDataLoading, sessionRecordingNavigation: nav } = useValues(
        sessionsTableLogic
    )
    const { loadSessionPlayer, closeSessionPlayer } = useActions(sessionsTableLogic)

    if (featureFlags['posthog-rrweb-player']) {
        return (
            <Drawer
                title="Session recording"
                width={window.innerWidth - 300}
                onClose={closeSessionPlayer}
                destroyOnClose={true}
                visible={true}
            >
                {sessionPlayerDataLoading ? <Loading /> : <Player events={sessionPlayerData} />}
            </Drawer>
        )
    }

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
                        <Button style={{ marginRight: 12 }} onClick={() => nav.prev && loadSessionPlayer(nav.prev)}>
                            Previous
                        </Button>
                    )}
                    {nav.next && <Button onClick={() => nav.next && loadSessionPlayer(nav.next)}>Next</Button>}
                </>
            }
        >
            {sessionPlayerDataLoading ? <Loading /> : <SessionsPlayer events={sessionPlayerData} />}
        </Drawer>
    )
}
