import React, { useEffect, useRef } from 'react'
import { useValues } from 'kea'
import { SessionRecordingPlayerProps } from '~/types'
import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import { Replayer } from 'rrweb'
import { toParams } from 'lib/utils'
import { eventWithTime } from 'rrweb/typings/types'
import api from 'lib/api'

export function SessionRecordingPreview({
    sessionRecordingId,
    recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
}: SessionRecordingPlayerProps): JSX.Element {
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }))
    const frame = useRef<HTMLDivElement | null>(null)
    const replayer = useRef<Replayer | null>(null)

    console.log({ sessionPlayerData })

    const loadPlayer = async (): Promise<void> => {
        if (!frame.current) {
            return
        }
        const params = toParams({
            recording_start_time: recordingStartTime,
            limit: 20,
        })
        const apiUrl = `api/projects/@current/session_recordings/${sessionRecordingId}/snapshots?${params}`
        const response = await api.get(apiUrl)

        // If we have a next url, we need to append the new snapshots to the existing ones
        const snapshotsByWindowId: { [key: string]: eventWithTime[] } = {}
        const incomingSnapshotByWindowId: {
            [key: string]: eventWithTime[]
        } = response.result?.snapshot_data_by_window_id
        Object.entries(incomingSnapshotByWindowId).forEach(([windowId, snapshots]) => {
            snapshotsByWindowId[windowId] = [...(snapshotsByWindowId[windowId] ?? []), ...snapshots]
        })

        const snapshots = snapshotsByWindowId[Object.keys(snapshotsByWindowId)[0]]

        replayer.current = new Replayer(snapshots, {
            root: frame.current,
            triggerFocus: false,
            insertStyleRules: [
                `.ph-no-capture {   background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjE2IiBoZWlnaHQ9IjE2IiBmaWxsPSJibGFjayIvPgo8cGF0aCBkPSJNOCAwSDE2TDAgMTZWOEw4IDBaIiBmaWxsPSIjMkQyRDJEIi8+CjxwYXRoIGQ9Ik0xNiA4VjE2SDhMMTYgOFoiIGZpbGw9IiMyRDJEMkQiLz4KPC9zdmc+Cg=="); }`,
            ],
        })

        replayer.current.pause(snapshots[snapshots.length - 1].timestamp)
    }

    useEffect(() => {
        loadPlayer()
    }, [frame])

    return (
        <div
            className="SessionRecordingPreview bg-default m-4 relative overflow-hidden"
            tabIndex={0}
            style={{ height: 200, width: 300 }}
        >
            <div
                className="player-frame"
                ref={frame}
                style={{ position: 'absolute', transform: 'scale(0.2)', transformOrigin: 'top left' }}
            />
        </div>
    )
}
