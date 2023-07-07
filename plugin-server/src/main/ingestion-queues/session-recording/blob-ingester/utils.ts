import { DateTime } from 'luxon'

import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.events,
    }
}

// Helper to return now as a milliseconds timestamp
export const now = () => DateTime.now().toMillis()
