import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'
import rrwebPlayer from 'rrweb-player'
import 'rrweb-player/dist/style.css'
import { eventWithTime } from 'rrweb/typings/types'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'

export default function SessionsPlayer({ events }: { events: eventWithTime[] }): JSX.Element {
    const target = useRef<HTMLDivElement | null>(null)

    const { sessionsPlayerSpeed } = useValues(sessionsTableLogic)
    const { setPlayerSpeed } = useActions(sessionsTableLogic)

    useEffect(() => {
        if (target.current && events) {
            const player = new rrwebPlayer({
                target: target.current,
                // eslint-disable-next-line
                // @ts-ignore
                props: {
                    width: 952,
                    events,
                    autoPlay: true,
                },
            })
            player.setSpeed(sessionsPlayerSpeed)

            player.getReplayer().on('state-change', () => {
                setPlayerSpeed(player.getReplayer().config.speed)
            })

            return () => player.pause()
        }
    }, [])

    return <div ref={target} id="sessions-player" />
}
