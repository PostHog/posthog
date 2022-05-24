import { StatsD } from 'hot-shots'
import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
import { ObjectStorage } from '../../main/services/objectStorage'
import { TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'

const { OBJECT_STORAGE_SESSION_RECORDING_FOLDER, OBJECT_STORAGE_BUCKET } = defaultConfig

export const processSnapshotData = async (
    timestamp: DateTime,
    session_id: string,
    snapshot_data: Record<any, any>,
    team_id: number,
    objectStorage: ObjectStorage,
    statsd: StatsD | undefined
): Promise<string> => {
    // As we don't want to store the session recording payload in ClickHouse,
    // let's intercept the event, parse the metadata and store the data in
    // our object storage system.

    if (!objectStorage.isEnabled) {
        return JSON.stringify(snapshot_data)
    }

    const teamIsOnSessionRecordingToS3AllowList = objectStorage.sessionRecordingAllowList.includes(team_id)

    if (!teamIsOnSessionRecordingToS3AllowList) {
        return JSON.stringify(snapshot_data)
    }

    const dateKey = castTimestampOrNow(timestamp, TimestampFormat.DateOnly)
    const object_storage_path = `${OBJECT_STORAGE_SESSION_RECORDING_FOLDER}/${dateKey}/${session_id}/${snapshot_data.chunk_id}/${snapshot_data.chunk_index}`
    const params = { Bucket: OBJECT_STORAGE_BUCKET, Key: object_storage_path, Body: snapshot_data.data }

    const tags = {
        team_id: team_id.toString(),
        session_id,
    }

    const storageWriteTimer = new Date()

    try {
        await objectStorage.putObject(params)
        statsd?.increment('session_data.storage_upload.success', tags)

        const altered_data = { ...snapshot_data }
        // don't delete the snapshot data **yet**, or if we have to roll back we lose data
        // this makes the timings less accurate because we're storing and loading the data twice
        // delete altered_data.data
        altered_data['object_storage_path'] = object_storage_path

        return JSON.stringify(altered_data)
    } catch (err) {
        statsd?.increment('session_data.storage_upload.error', tags)
        return JSON.stringify(snapshot_data)
    } finally {
        statsd?.timing('session_data.storage_upload.timing', storageWriteTimer, tags)
    }
}
