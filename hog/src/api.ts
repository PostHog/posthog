import type { Credentials } from './credentials'
import { HogError } from './errors'

export interface ApiResponse {
    ok: boolean
    status: number
    body: unknown
}

export class PostHogApi {
    constructor(
        private readonly credentials: Credentials,
        private readonly fetchFn: typeof fetch,
        private readonly userAgent: string
    ) {}

    environmentUrl(path: string): URL {
        const base = new URL(`api/environments/${this.credentials.projectId}/`, this.credentials.host)
        return new URL(path, base)
    }

    async postEnvironment(path: string, payload: unknown): Promise<ApiResponse> {
        const url = this.environmentUrl(path)
        let response: Response
        try {
            response = await this.fetchFn(url, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${this.credentials.apiKey}`,
                    'Content-Type': 'application/json',
                    'User-Agent': this.userAgent,
                },
                body: JSON.stringify(payload),
            })
        } catch (error) {
            throw new HogError(
                'network_error',
                `hog couldn't reach ${this.credentials.host}: ${error instanceof Error ? error.message : String(error)}`,
                'Check the host and your network connection.'
            )
        }

        const text = await response.text()
        let body: unknown
        try {
            body = JSON.parse(text)
        } catch {
            throw new HogError(
                'unexpected_response',
                `PostHog answered with HTTP ${response.status} and a body that isn't JSON.`,
                response.status === 404 ? 'Check the host and the project ID.' : undefined
            )
        }
        return { ok: response.ok, status: response.status, body }
    }
}
