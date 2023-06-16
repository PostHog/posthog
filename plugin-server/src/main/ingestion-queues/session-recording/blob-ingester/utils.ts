import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.events,
    }
}
