import { Headers, RequestInfo, RequestInit, Response } from 'node-fetch'

import { trackedFetch } from './fetch'
import { UUIDT } from './utils'

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
    const id = new UUIDT().toString()
    const requestTimestamp = new Date()

    // Record request details
    const request: RecordedRequest = {
        url: url.toString(),
        method: init?.method || 'GET',
        headers: init?.headers ? convertHeadersToRecord(init.headers) : {},
        body: init?.body ? convertBodyToString(init.body) : null,
        timestamp: requestTimestamp,
    }

    try {
        // Make the actual request using the original trackedFetch
        // Pass init exactly as received to maintain compatibility with tests
        const response = await trackedFetch(url, init)

        // Handle the case where the response might be mocked in tests
        // In tests, the response might not have all the methods of a real Response
        let responseBody: string | null = null
        const responseHeaders: Record<string, string> = {}

        try {
            // Try to clone and read the response body
            if (response.clone && typeof response.clone === 'function') {
                const clonedResponse = response.clone()
                responseBody = await clonedResponse.text()
            }

            // Try to read the headers
            if (response.headers && typeof response.headers.forEach === 'function') {
                response.headers.forEach((value, key) => {
                    responseHeaders[key.toLowerCase()] = value
                })
            }
        } catch (e) {
            // If we can't clone or read the response, just continue
            // This might happen in tests where the response is mocked
        }

        // Record response details
        const recordedResponse: RecordedResponse = {
            status: response.status || 200,
            statusText: response.statusText || 'OK',
            headers: responseHeaders,
            body: responseBody,
            timestamp: new Date(),
        }

        // Add the recorded call to the recorder
        recorder.addCall({
            id,
            request,
            response: recordedResponse,
        })

        return response
    } catch (err) {
        const error = err as Error

        // Record error details
        const recordedResponse: RecordedResponse = {
            status: 0,
            statusText: error.message,
            headers: {},
            body: null,
            timestamp: new Date(),
        }

        // Add the recorded call to the recorder
        recorder.addCall({
            id,
            request,
            response: recordedResponse,
            error,
        })

        // Just rethrow the original error
        throw error
    }
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
function convertBodyToString(body: any): string | null {
    if (body === null || body === undefined) {
        return null
    }

    // Handle string bodies (already stringified JSON or plain text)
    if (typeof body === 'string') {
        return body
    }

    // Handle URLSearchParams for form submissions
    if (body instanceof URLSearchParams) {
        return body.toString()
    }

    // For objects, try to stringify them as JSON
    if (typeof body === 'object' && body !== null) {
        try {
            return JSON.stringify(body)
        } catch {
            return '[Object]'
        }
    }

    // For any other types, convert to string
    return String(body)
}
