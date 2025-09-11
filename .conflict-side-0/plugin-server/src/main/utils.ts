import { SessionRecordingV2MetadataSwitchoverDate } from '~/types'

import { logger } from '../utils/logger'

export const eventPassesMetadataSwitchoverTest = (
    timestamp: number,
    metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate
): boolean => {
    if (metadataSwitchoverDate === null) {
        return false
    }

    if (metadataSwitchoverDate === true) {
        return true
    }

    return timestamp >= metadataSwitchoverDate.getTime()
}

export const parseSessionRecordingV2MetadataSwitchoverDate = (
    config: string | null | undefined
): SessionRecordingV2MetadataSwitchoverDate => {
    let metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate = null
    if (config === '*') {
        metadataSwitchoverDate = true
        logger.info('SESSION_RECORDING_V2_METADATA_SWITCHOVER asterisk enabled', {
            value: config,
        })
    } else if (config) {
        const parsed = Date.parse(config)
        if (!isNaN(parsed)) {
            metadataSwitchoverDate = new Date(parsed)
            logger.info('SESSION_RECORDING_V2_METADATA_SWITCHOVER enabled', {
                value: config,
                parsedDate: metadataSwitchoverDate.toISOString(),
            })
        } else {
            throw new Error('SESSION_RECORDING_V2_METADATA_SWITCHOVER is not a valid ISO datetime or "*": ' + config)
        }
    }
    return metadataSwitchoverDate
}
