export interface ApiClientConfig {
    apiToken: string
    baseUrl: string
    clientUserAgent?: string
}

export interface ApiRequestOptions {
    method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
    path: string
    body?: any
    query?: Record<string, any>
}

export class ApiClient {
    private config: ApiClientConfig

    constructor(config: ApiClientConfig) {
        this.config = config
    }

    async request<T = any>({ method, path, body, query }: ApiRequestOptions): Promise<T> {
        // Reject absolute and protocol-relative URLs. `new URL('//other.com', base)`
        // returns `https://other.com` — which would leak the Authorization header to
        // an arbitrary host.
        if (/^(https?:)?\/\//i.test(path)) {
            throw new Error(`API path must be relative, not an absolute or protocol-relative URL: ${path}`)
        }

        const url = new URL(path.startsWith('/') ? path : `/api/${path}`, this.config.baseUrl)

        const configuredHost = new URL(this.config.baseUrl).host
        if (url.host !== configuredHost) {
            throw new Error(`Resolved URL host '${url.host}' does not match configured host '${configuredHost}'`)
        }

        // Add query parameters
        if (query) {
            Object.entries(query).forEach(([key, value]) => {
                if (value !== undefined && value !== null) {
                    url.searchParams.append(key, String(value))
                }
            })
        }

        // Prepare request options
        const requestInit: RequestInit = {
            method,
            headers: {
                Authorization: `Bearer ${this.config.apiToken}`,
                'Content-Type': 'application/json',
                'User-Agent': this.config.clientUserAgent || 'PostHog-CLI/2.0',
            },
        }

        // Add body for non-GET requests
        if (body && method !== 'GET') {
            requestInit.body = JSON.stringify(body)
        }

        try {
            const response = await fetch(url.toString(), requestInit)

            if (!response.ok) {
                const errorText = await response.text()
                throw new Error(`API request failed: ${response.status} ${response.statusText} - ${errorText}`)
            }

            if (response.status === 204) {
                return undefined as T
            }
            const text = await response.text()
            return (text ? JSON.parse(text) : undefined) as T
        } catch (error) {
            if (error instanceof Error) {
                throw error
            }
            throw new Error(`API request failed: ${String(error)}`)
        }
    }
}
