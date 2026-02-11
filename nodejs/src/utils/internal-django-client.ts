/**
 * Internal API client for secure service-to-service communication to Django.
 *
 * This module provides utilities for Node.js services to make authenticated
 * requests to Django internal APIs using the shared INTERNAL_API_SECRET.
 *
 * Example usage:
 *     import { internalDjangoRequest } from '~/utils/internal-django-client'
 *
 *     const response = await internalDjangoRequest(config, 'https://django-api/internal/endpoint', {
 *         method: 'POST',
 *         body: JSON.stringify({ data: 'value' }),
 *     })
 */
import type { PluginsServerConfig } from '../types'
import { type FetchOptions, type FetchResponse, internalFetch } from './request'

const HEADER_NAME = 'X-Internal-Api-Secret'

export interface InternalDjangoRequestOptions extends FetchOptions {}

/**
 * Make an authenticated request to a Django internal API endpoint.
 *
 * Automatically adds the X-Internal-Api-Secret header for authentication.
 *
 * @param config - Server configuration containing INTERNAL_API_SECRET
 * @param url - Full URL to the Django endpoint
 * @param options - Request options (method, body, headers, etc.)
 * @returns Promise resolving to the fetch response
 *
 * @example
 * const response = await internalDjangoRequest(config, 'https://api/internal/data', {
 *     method: 'POST',
 *     headers: { 'Content-Type': 'application/json' },
 *     body: JSON.stringify({ key: 'value' }),
 * })
 * const data = await response.json()
 */
export async function internalDjangoRequest(
    config: Pick<PluginsServerConfig, 'INTERNAL_API_SECRET'>,
    url: string,
    options: InternalDjangoRequestOptions = {}
): Promise<FetchResponse> {
    const headers: Record<string, string> = {
        ...(options.headers || {}),
    }

    // Add internal API secret header if configured
    if (config.INTERNAL_API_SECRET) {
        headers[HEADER_NAME] = config.INTERNAL_API_SECRET
    }

    return await internalFetch(url, {
        ...options,
        headers,
    })
}

/**
 * Get internal API headers for manual request construction.
 *
 * Use this when you need to add authentication headers to a request
 * that isn't using internalDjangoRequest (e.g., with a different HTTP client).
 *
 * @param config - Server configuration containing INTERNAL_API_SECRET
 * @returns Headers object with authentication
 *
 * @example
 * const headers = getInternalApiHeaders(config)
 * const response = await someOtherHttpClient.get(url, { headers })
 */
export function getInternalApiHeaders(
    config: Pick<PluginsServerConfig, 'INTERNAL_API_SECRET'>
): Record<string, string> {
    if (!config.INTERNAL_API_SECRET) {
        return {}
    }

    return {
        [HEADER_NAME]: config.INTERNAL_API_SECRET,
    }
}
