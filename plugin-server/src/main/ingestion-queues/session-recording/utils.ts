import { DateTime } from 'luxon'
import path from 'path'

import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.events,
    }
}

// Helper to return now as a milliseconds timestamp
export const now = () => DateTime.now().toMillis()

export const minDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return Math.min(...definedArgs)
}

export const maxDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return Math.max(...definedArgs)
}

export const bufferFileDir = (root: string) => path.join(root, 'session-buffer-files')
