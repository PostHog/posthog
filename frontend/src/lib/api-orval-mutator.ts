/**
 * Custom orval mutator that wraps PostHog's api module.
 * This allows generated API clients to use the same HTTP client as the rest of the app.
 *
 * Orval calls: apiMutator(url, { method, body, signal, ... })
 */
import api from 'lib/api'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

interface RequestOptions extends RequestInit {
    method: HttpMethod
    body?: string
}

export const apiMutator = async <T>(url: string, options: RequestOptions): Promise<T> => {
    const { method, body, signal } = options
    const data = body ? JSON.parse(body) : undefined
    const apiOptions = signal ? { signal } : undefined

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
