import React from 'react'
import { eventWithTime } from 'rrweb/typings/types'
import { SessionType } from '~/types'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Modal } from 'antd'
import { green } from '@ant-design/colors'
import SessionsPlayer from './SessionsPlayer'

interface SessionsPlayerButtonProps {
    session: SessionType
}

export default function SessionsPlayerButton({ session }: SessionsPlayerButtonProps): JSX.Element | null {
    function showSessionPlayer(events: eventWithTime[]): void {
        Modal.info({
            centered: true,
            content: <SessionsPlayer events={events}></SessionsPlayer>,
            icon: null,
            okType: 'primary',
            okText: 'Done',
            width: 1000,
        })
    }

    const snapshotEventsData: eventWithTime[] = session.events
        .filter((event) => event.event === '$snapshot')
        .map((event) => event.properties?.$snapshot_data)
    if (snapshotEventsData.length < 2) return null

    return (
        <PlayCircleOutlined
            style={{ color: green.primary }}
            onClick={(event: React.MouseEvent) => {
                event.stopPropagation()
                showSessionPlayer(snapshotEventsData)
            }}
        ></PlayCircleOutlined>
    )
}
