import { Headers, RequestInfo, RequestInit, Response } from 'node-fetch'
import { Counter } from 'prom-client'

import { defaultConfig } from '../config/config'
import { trackedFetch } from './fetch'
import { parseJSON } from './json-parse'
import { UUIDT } from './utils'

const pluginFetchCounter = new Counter({
    name: 'plugin_fetch_count',
    help: 'The number of plugin fetches',
})

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

export interface ComparisonResult {
    matches: boolean
    details: {
        matchedCalls: number
        totalCalls1: number
        totalCalls2: number
        mismatchDetails: Array<{
            index1: number
            index2: number
            differences: string[] // Human-readable difference messages
        }>
    }
}

const PROPERTY_DIFFS_TO_IGNORE = new Set(['sentAt'])

export class HttpCallRecorder {
    private calls: RecordedHttpCall[] = []

    public getCalls(): RecordedHttpCall[] {
        return [...this.calls]
    }

    public clearCalls(): void {
        this.calls = []
    }

    public addCall(call: RecordedHttpCall): void {
        this.calls.push(call)
    }

    /**
     * Compares two sets of HTTP calls to determine if they match based on key properties.
     * Differences are reported as human-readable strings in the format:
     * - For URLs: "Call X: Expected [legacy] <url1> but got [hogfn] <url2>"
     * - For methods: "Call X: Expected [legacy] <method1> but got [hogfn] <method2>"
     * - For bodies: "Call X: Request body differences: <path>: [legacy] <value1> ≠ [hogfn] <value2>"
     *
     * @param legacyCalls First set of recorded HTTP calls from legacy plugin
     * @param hogFnCalls Second set of recorded HTTP calls from hogfunction
     * @returns Comparison result with details about matches and mismatches
     */
    public compareCalls(legacyCalls: RecordedHttpCall[], hogFnCalls: RecordedHttpCall[]): ComparisonResult {
        const result: ComparisonResult = {
            matches: true,
            details: {
                matchedCalls: 0,
                totalCalls1: legacyCalls.length,
                totalCalls2: hogFnCalls.length,
                mismatchDetails: [],
            },
        }

        // If call counts don't match, we already know they're different
        if (legacyCalls.length !== hogFnCalls.length) {
            result.matches = false
            result.details.mismatchDetails.push({
                index1: 0,
                index2: 0,
                differences: [
                    `Call sequence length mismatch: expected ${legacyCalls.length} calls but got ${hogFnCalls.length} calls`,
                ],
            })
            return result
        }

        // Compare calls in strict order
        for (let i = 0; i < legacyCalls.length; i++) {
            const differences = this.compareHttpCalls(legacyCalls[i], hogFnCalls[i], i)
            if (differences.length > 0) {
                result.matches = false
                result.details.mismatchDetails.push({
                    index1: i,
                    index2: i,
                    differences,
                })
            } else {
                result.details.matchedCalls++
            }
        }

        return result
    }

    private compareHttpCalls(call1: RecordedHttpCall, call2: RecordedHttpCall, index: number): string[] {
        const differences: string[] = []

        // Compare request method - always check method regardless of type
        if (call1.request.method !== call2.request.method) {
            differences.push(
                `Call ${index + 1}: Expected [legacy] ${call1.request.method} but got [hogfn] ${call2.request.method}`
            )
            return differences
        }

        // Compare URLs for all requests
        if (call1.request.url !== call2.request.url) {
            differences.push(
                `Call ${index + 1}: Expected [legacy] ${call1.request.method} ${call1.request.url} but got [hogfn] ${
                    call2.request.method
                } ${call2.request.url}`
            )
            // For GET requests, we only care about URL differences
            if (call1.request.method === 'GET') {
                return differences
            }
        }

        // For non-GET requests, compare request bodies if they exist
        if (call1.request.body || call2.request.body) {
            try {
                const body1 = call1.request.body ? parseJSON(call1.request.body) : null
                const body2 = call2.request.body ? parseJSON(call2.request.body) : null
                const bodyDiffs = this.findObjectDifferences(body1, body2, '', index + 1)
                differences.push(...bodyDiffs)
            } catch {
                // If parsing fails, compare as strings
                if (call1.request.body !== call2.request.body) {
                    differences.push(
                        `Call ${index + 1}: Request body differences: body: [legacy] ${call1.request.body} ≠ [hogfn] ${
                            call2.request.body
                        }`
                    )
                }
            }
        }

        return differences
    }

    private findObjectDifferences(obj1: any, obj2: any, path: string = '', callNumber: number): string[] {
        const differences: string[] = []

        // Handle primitive types
        if (obj1 === obj2) {
            return differences
        }

        // If either is not an object or is null, they're different
        if (typeof obj1 !== 'object' || obj1 === null || typeof obj2 !== 'object' || obj2 === null) {
            return [
                `Call ${callNumber}: Request body differences: ${path || 'body'}: [legacy] ${JSON.stringify(
                    obj1
                )} ≠ [hogfn] ${JSON.stringify(obj2)}`,
            ]
        }

        // Handle arrays
        if (Array.isArray(obj1) && Array.isArray(obj2)) {
            if (obj1.length !== obj2.length) {
                return [
                    `Call ${callNumber}: Request body differences: ${path || 'body'}: [legacy] ${JSON.stringify(
                        obj1
                    )} ≠ [hogfn] ${JSON.stringify(obj2)}`,
                ]
            }

            // Compare array elements
            for (let i = 0; i < obj1.length; i++) {
                const elementDiffs = this.findObjectDifferences(
                    obj1[i],
                    obj2[i],
                    path ? `${path}[${i}]` : `[${i}]`,
                    callNumber
                )
                differences.push(...elementDiffs)
            }
            return differences
        }

        // If one is array and the other is not, they're different
        if (Array.isArray(obj1) || Array.isArray(obj2)) {
            return [
                `Call ${callNumber}: Request body differences: ${path || 'body'}: [legacy] ${JSON.stringify(
                    obj1
                )} ≠ [hogfn] ${JSON.stringify(obj2)}`,
            ]
        }

        // Compare object keys
        const keys1 = Object.keys(obj1)
        const keys2 = Object.keys(obj2)

        // Find keys that exist in obj1 but not in obj2
        for (const key of keys1) {
            if (!(key in obj2)) {
                differences.push(
                    `Call ${callNumber}: Request body differences: ${
                        path ? `${path}.${key}` : key
                    }: [legacy] ${JSON.stringify(obj1[key])} ≠ [hogfn] undefined`
                )
                continue
            }

            if (PROPERTY_DIFFS_TO_IGNORE.has(key)) {
                continue
            }

            const valueDiffs = this.findObjectDifferences(
                obj1[key],
                obj2[key],
                path ? `${path}.${key}` : key,
                callNumber
            )
            differences.push(...valueDiffs)
        }

        // Find keys that exist in obj2 but not in obj1
        for (const key of keys2) {
            if (!(key in obj1)) {
                differences.push(
                    `Call ${callNumber}: Request body differences: ${
                        path ? `${path}.${key}` : key
                    }: [legacy] undefined ≠ [hogfn] ${JSON.stringify(obj2[key])}`
                )
            }
        }

        return differences
    }
}

// Global recorder instance
export const globalHttpCallRecorder = new HttpCallRecorder()

export function getHttpCallRecorder(): HttpCallRecorder {
    return globalHttpCallRecorder
}

/**
 * A wrapper around trackedFetch that conditionally records HTTP requests and responses.
 * If recording is disabled, it simply passes through to trackedFetch.
 *
 * The recorder captures:
 * - Full request details (URL, method, headers, body)
 * - Full response details (status, headers, body)
 * - Any errors that occur during the request
 *
 * This is used for comparing HTTP calls between legacy plugins and hogfunctions
 * to ensure they make the same API calls.
 */
export async function recordedFetch(url: RequestInfo, init?: RequestInit): Promise<Response> {
    // Check if recording should be enabled based on config flags
    const shouldRecordHttpCalls =
        defaultConfig.DESTINATION_MIGRATION_DIFFING_ENABLED === true && defaultConfig.TASKS_PER_WORKER === 1

    pluginFetchCounter.inc()

    // If recording is disabled, just use trackedFetch directly
    if (!shouldRecordHttpCalls) {
        return trackedFetch(url, init)
    }

    let id: string
    let request: RecordedRequest
    try {
        id = new UUIDT().toString()
        request = recordFetchRequest(url, init)
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

export function recordFetchRequest(url: RequestInfo, init?: RequestInit): RecordedRequest {
    return {
        url: url.toString(),
        method: init?.method || 'GET',
        headers: init?.headers ? convertHeadersToRecord(init.headers) : {},
        body: init?.body ? convertBodyToString(init.body) : null,
        timestamp: new Date(),
    }
}

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
