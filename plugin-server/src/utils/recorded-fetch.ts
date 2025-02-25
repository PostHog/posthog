import { Headers, RequestInfo, RequestInit, Response } from 'node-fetch'

import { trackedFetch } from './fetch'

export interface RecordedRequest {
    url: string
    method: string
    headers: Record<string, string>
    body?: string | null
    timestamp: Date
}

export interface RecordedResponse {
    status: number
    statusText: string
    headers: Record<string, string>
    body: string | null
    timestamp: Date
}

export interface RecordedHttpCall {
    id: string
    request: RecordedRequest
    response: RecordedResponse
    duration: number
    error?: Error
}

export class HttpCallRecorder {
    private calls: RecordedHttpCall[] = []

    public getCalls(): RecordedHttpCall[] {
        return [...this.calls]
    }

    public clearCalls(): void {
        this.calls = []
    }

    // This method is needed internally by recordedFetch
    public addCall(call: RecordedHttpCall): void {
        this.calls.push(call)
    }
}

/**
 * A wrapper around trackedFetch that records HTTP requests and responses
 * without altering the original functionality.
 */
export async function recordedFetch(
    recorder: HttpCallRecorder,
    url: RequestInfo,
    init?: RequestInit
): Promise<Response> {
    const id = generateCallId()
    const requestStartTime = Date.now()
    const requestTimestamp = new Date()

    // Clone the request init to avoid modifying the original
    const requestInit = init ? { ...init } : {}

    // Record request details
    const request: RecordedRequest = {
        url: url.toString(),
        method: requestInit.method || 'GET',
        headers: requestInit.headers ? convertHeadersToRecord(requestInit.headers) : {},
        body: requestInit.body ? await convertBodyToString(requestInit.body) : null,
        timestamp: requestTimestamp,
    }

    let response: Response
    let error: Error | undefined

    try {
        // Make the actual request using the original trackedFetch
        response = await trackedFetch(url, requestInit)

        // Clone the response to read the body without consuming it
        const clonedResponse = response.clone()
        const responseBody = await clonedResponse.text()

        // Extract headers from response
        const responseHeaders: Record<string, string> = {}
        response.headers.forEach((value, key) => {
            responseHeaders[key.toLowerCase()] = value
        })

        // Record response details
        const recordedResponse: RecordedResponse = {
            status: response.status,
            statusText: response.statusText,
            headers: responseHeaders,
            body: responseBody,
            timestamp: new Date(),
        }

        // Calculate duration
        const duration = Date.now() - requestStartTime

        // Add the recorded call to the recorder
        recorder.addCall({
            id,
            request,
            response: recordedResponse,
            duration,
        })

        return response
    } catch (err) {
        error = err as Error

        // Record error details
        const recordedResponse: RecordedResponse = {
            status: 0,
            statusText: error.message,
            headers: {},
            body: null,
            timestamp: new Date(),
        }

        // Calculate duration
        const duration = Date.now() - requestStartTime

        // Add the recorded call to the recorder
        recorder.addCall({
            id,
            request,
            response: recordedResponse,
            duration,
            error,
        })

        throw error
    }
}

/**
 * Generate a unique ID for a recorded HTTP call
 */
function generateCallId(): string {
    return `call_${Date.now()}_${Math.random().toString(36).substring(2, 15)}`
}

/**
 * Convert headers to a simple record for storage
 */
function convertHeadersToRecord(headers: any): Record<string, string> {
    const record: Record<string, string> = {}

    if (headers instanceof Headers) {
        headers.forEach((value, key) => {
            record[key.toLowerCase()] = value
        })
    } else if (Array.isArray(headers)) {
        for (const [key, value] of headers) {
            record[key.toLowerCase()] = value
        }
    } else if (headers && typeof headers === 'object') {
        Object.entries(headers).forEach(([key, value]) => {
            record[key.toLowerCase()] = String(value)
        })
    }

    return record
}

/**
 * Convert request body to string for recording
 */
async function convertBodyToString(body: any): Promise<string | null> {
    if (body === null || body === undefined) {
        return null
    }

    if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) {
        return '[Binary data]'
    }

    if (body instanceof URLSearchParams) {
        return body.toString()
    }

    if (typeof body === 'string') {
        return body
    }

    if (typeof body === 'object' && body !== null) {
        if (typeof body.pipe === 'function') {
            return '[Stream data]'
        }

        if (typeof body.getBoundary === 'function') {
            return '[FormData]'
        }

        // Handle Blob objects
        if (typeof body.text === 'function') {
            try {
                return await body.text()
            } catch {
                return '[Blob data]'
            }
        }

        // For regular objects
        try {
            return JSON.stringify(body)
        } catch {
            return '[Unserializable object]'
        }
    }

    // For any other types
    try {
        return String(body)
    } catch {
        return '[Unserializable data]'
    }
}
