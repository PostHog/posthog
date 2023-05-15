import zlib from 'node:zlib'

import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

// NOTE: These functions are meant to be identical to those in posthog/session_recordings/session_recording_helpers.py
export function compressToString(input: string): string {
    const compressed_data = zlib.gzipSync(Buffer.from(input, 'utf16le'))
    return compressed_data.toString('base64')
}

export function decompressFromString(input: string, doubleDecode = false): string {
    if (doubleDecode) {
        input = Buffer.from(input, 'base64').toString()
    }
    const compressedData = Buffer.from(input, 'base64')
    try {
        const uncompressed = zlib.gunzipSync(compressedData)
        // Trim is a quick way to get rid of BOMs created by python
        return uncompressed.toString('utf16le').trim()
    } catch (e: any) {
        if (e.code === 'Z_DATA_ERROR' && e.errno === -3 && !doubleDecode) {
            // some received data (particularly chunks) are double encoded
            return decompressFromString(input, true)
        }
        let message = `Failed to decompress data: ${e.message}`
        if (doubleDecode) {
            message += 'even accounting for double decoding'
        }
        throw new Error(message)
    }
}

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: decompressFromString(message.data),
    }
}
