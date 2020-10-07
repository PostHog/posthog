import React, { useEffect, useRef } from 'react'
import rrwebPlayer from 'rrweb-player'
import 'rrweb-player/dist/style.css'
import { eventWithTime } from 'rrweb/typings/types'

export default function SessionsPlayer({ events }: { events: eventWithTime[] }): JSX.Element {
    const target = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (target.current) {
            new rrwebPlayer({
                target: target.current,
                // eslint-disable-next-line
                // @ts-ignore
                props: {
                    width: 900,
                    events,
                    autoPlay: true,
                },
            })
        }
    }, [])

    return <div ref={target} id="sessions-player"></div>
}
