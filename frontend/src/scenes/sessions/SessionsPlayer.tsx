import { useValues } from 'kea'
import { Loading } from 'lib/utils'
import React, { useEffect, useRef } from 'react'
import rrwebPlayer from 'rrweb-player'
import 'rrweb-player/dist/style.css'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'

export default function SessionsPlayer(): JSX.Element {
    const target = useRef<HTMLDivElement | null>(null)
    const { sessionPlayerData, sessionPlayerDataLoading } = useValues(sessionsTableLogic)

    useEffect(() => {
        if (target.current && !sessionPlayerDataLoading) {
            const player = new rrwebPlayer({
                target: target.current,
                // eslint-disable-next-line
                // @ts-ignore
                props: {
                    width: 900,
                    events: sessionPlayerData,
                    autoPlay: true,
                },
            })

            return () => player.pause()
        }
    }, [sessionPlayerDataLoading])

    return sessionPlayerDataLoading ? <Loading /> : <div ref={target} id="sessions-player"></div>
}
