import { Headers, RequestInfo, RequestInit, Response } from 'node-fetch'

import { defaultConfig } from '../config/config'
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

// Global recorder instance
export const globalHttpCallRecorder = new HttpCallRecorder()

// Export the recorder to make it accessible for inspection
export function getHttpCallRecorder(): HttpCallRecorder {
    return globalHttpCallRecorder
}

/**
 * A wrapper around trackedFetch that conditionally records HTTP requests and responses
 * based on config flags. If recording is disabled, it simply passes through to trackedFetch.
 */
export async function recordedFetch(url: RequestInfo, init?: RequestInit): Promise<Response> {
    // Check if recording should be enabled based on config flags
    const shouldRecordHttpCalls =
        defaultConfig.DESTINATION_MIGRATION_DIFFING_ENABLED === true && defaultConfig.TASKS_PER_WORKER === 1

    // If recording is disabled, just use trackedFetch directly
    if (!shouldRecordHttpCalls) {
        return trackedFetch(url, init)
    }

    let id: string
    let request: RecordedRequest
    try {
        id = new UUIDT().toString()
        request = {
            url: url.toString(),
            method: init?.method || 'GET',
            headers: init?.headers ? convertHeadersToRecord(init.headers) : {},
            body: init?.body ? convertBodyToString(init.body) : null,
            timestamp: new Date(),
        }
    } catch {
        // If recording setup fails, just do the fetch
        return trackedFetch(url, init)
    }

    let response: Response
    try {
        response = await trackedFetch(url, init)
    } catch (error) {
        try {
            globalHttpCallRecorder.addCall({
                id,
                request,
                response: {
                    status: 0,
                    statusText: (error as Error).message,
                    headers: {},
                    body: null,
                    timestamp: new Date(),
                },
                error: error as Error,
            })
        } catch {} // Ignore recording errors
        throw error
    }

    // Try to record successful response
    try {
        const clonedResponse = response.clone()
        const responseBody = await clonedResponse.text()
        const responseHeaders: Record<string, string> = {}
        response.headers.forEach((value, key) => {
            responseHeaders[key.toLowerCase()] = value
        })

        globalHttpCallRecorder.addCall({
            id,
            request,
            response: {
                status: response.status,
                statusText: response.statusText,
                headers: responseHeaders,
                body: responseBody,
                timestamp: new Date(),
            },
        })
    } catch {} // Ignore recording errors

    return response
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
