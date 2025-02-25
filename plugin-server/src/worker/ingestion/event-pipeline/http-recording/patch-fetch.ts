import { v4 as uuidv4 } from 'uuid'

import { DestinationHttpRecorder } from './recorder'
import { HttpInteraction } from './types'

/**
 * Patches the trackedFetch function to record HTTP interactions
 */
export function patchTrackedFetch(trackedFetchModule: any, recorder: DestinationHttpRecorder): void {
    // Save the original function directly on the module
    if (!trackedFetchModule.__originalTrackedFetch) {
        trackedFetchModule.__originalTrackedFetch = trackedFetchModule.trackedFetch
    }

    // Replace the trackedFetch function with our recording version
    trackedFetchModule.trackedFetch = async (url: string, options: any = {}) => {
        const requestId = uuidv4()
        const startTime = Date.now()

        // Extract request details
        const method = options.method || 'GET'
        const headers = options.headers || {}
        const body = options.body
            ? typeof options.body === 'string'
                ? options.body.startsWith('{')
                    ? JSON.parse(options.body)
                    : options.body
                : options.body
            : undefined

        // Create request part of the interaction
        const interaction: Partial<HttpInteraction> = {
            id: requestId,
            timestamp: startTime,
            request: {
                method,
                url,
                headers,
                body,
            },
        }

        try {
            // Make the actual request using the original function
            const response = await trackedFetchModule.__originalTrackedFetch(url, options)
            const endTime = Date.now()

            // Extract response details
            const responseHeaders: Record<string, string> = {}
            response.headers.forEach((value: string, key: string) => {
                responseHeaders[key] = value
            })

            // Try to parse response body based on content type
            let responseBody
            const contentType = response.headers.get('content-type')

            // Clone the response to read the body without consuming it
            const clonedResponse = response.clone()

            if (contentType?.includes('application/json')) {
                try {
                    responseBody = await clonedResponse.json()
                } catch (e) {
                    // If we can't parse as JSON, get as text
                    responseBody = await clonedResponse.text()
                }
            } else if (contentType?.includes('text/')) {
                responseBody = await clonedResponse.text()
            }

            // Complete the interaction with response data
            interaction.response = {
                status: response.status,
                headers: responseHeaders,
                body: responseBody,
                timing: {
                    duration: endTime - startTime,
                },
            }

            // Record the complete interaction
            recorder.recordInteraction(interaction as HttpInteraction)

            return response
        } catch (error) {
            const endTime = Date.now()

            // Record failed request
            interaction.response = {
                status: 0,
                headers: {},
                body: { error: error.message },
                timing: {
                    duration: endTime - startTime,
                },
            }

            recorder.recordInteraction(interaction as HttpInteraction)

            throw error
        }
    }
}

/**
 * Restores the original trackedFetch function
 */
export function restoreTrackedFetch(trackedFetchModule: any): void {
    if (trackedFetchModule.__originalTrackedFetch) {
        trackedFetchModule.trackedFetch = trackedFetchModule.__originalTrackedFetch
        delete trackedFetchModule.__originalTrackedFetch
    }
}
