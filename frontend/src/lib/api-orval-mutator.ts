/**
 * Custom orval mutator that wraps PostHog's api module.
 * This allows generated API clients to use the same HTTP client as the rest of the app.
 *
 * Orval calls: apiMutator(url, { method, body, signal, ... })
 */
import api from 'lib/api'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

export const apiMutator = async <T>(url: string, options: RequestInit & { method: HttpMethod }): Promise<T> => {
    const { method, body, signal, headers } = options
    // Handle both JSON strings and FormData bodies
    const data = body ? (typeof body === 'string' ? JSON.parse(body) : body) : undefined
    // Convert Headers object to plain object if needed
    let headersObj: Record<string, string> | undefined
    if (headers instanceof Headers) {
        headersObj = {}
        headers.forEach((value, key) => {
            headersObj![key] = value
        })
    } else if (headers) {
        headersObj = headers as Record<string, string>
    }
    const apiOptions = signal ? { signal, headers: headersObj } : { headers: headersObj }

    switch (method) {
        case 'GET':
            return api.get(url, apiOptions)
        case 'POST':
            return api.create(url, data, apiOptions)
        case 'PUT':
            return api.put(url, data, apiOptions)
        case 'PATCH':
            return api.update(url, data, apiOptions)
        case 'DELETE':
            return api.delete(url)
        default:
            throw new Error(`Unsupported HTTP method: ${method}`)
    }
}

export default apiMutator
