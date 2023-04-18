import zlib from 'node:zlib'

import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

// NOTE: These functions are meant to be identical to those in posthog/session_recordings/session_recording_helpers.py
export function compressToString(input: string): string {
    const compressed_data = zlib.gzipSync(Buffer.from(input, 'utf16le'))
    return compressed_data.toString('base64')
}

export function decompressFromString(input: string): string {
    const compressedData = Buffer.from(input, 'base64')
    const uncompressed = zlib.gunzipSync(compressedData)
    // Trim is quick way to get rid of BOMs created by python
    return uncompressed.toString('utf16le').trim()
}

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: decompressFromString(message.data),
    }
}
