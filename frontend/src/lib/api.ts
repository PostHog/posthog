import posthog from 'posthog-js'
import { ActionType, TeamType } from '../types'

export function getCookie(name: string): string | null {
    let cookieValue: string | null = null
    if (document.cookie && document.cookie !== '') {
        for (let cookie of document.cookie.split(';')) {
            cookie = cookie.trim()
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === name + '=') {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
                break
            }
        }
    }
    return cookieValue
}

async function getJSONOrThrow(response: Response): Promise<any> {
    try {
        return await response.json()
    } catch (e) {
        return { statusText: response.statusText }
    }
}

class ApiRequest {
    private pathComponents: string[]
    private queryString: string | undefined

    constructor() {
        this.pathComponents = []
    }

    // URL assembly

    public assembleEndpointUrl(): string {
        let url = this.pathComponents.join('/')
        if (this.queryString) {
            if (!this.queryString.startsWith('?')) {
                url += '?'
            }
            url += this.queryString
        }
        return url
    }

    public assembleFullUrl(includeLeadingSlash = false): string {
        return (includeLeadingSlash ? '/api/' : 'api/') + this.assembleEndpointUrl()
    }

    // Endpoint composition

    public withAction(apiAction: string): ApiRequest {
        this.pathComponents.push(apiAction)
        return this
    }

    public withQueryString(queryString?: string): ApiRequest {
        this.queryString = queryString
        return this
    }

    public projectsList(): ApiRequest {
        this.pathComponents.push('projects')
        return this
    }

    public projectsDetail(id: TeamType['id']): ApiRequest {
        this.projectsList()
        this.pathComponents.push(id.toString())
        return this
    }

    public actionsList(teamId: TeamType['id']): ApiRequest {
        this.projectsDetail(teamId)
        this.pathComponents.push('actions')
        return this
    }

    public actionsDetail(teamId: TeamType['id'], actionId: ActionType['id']): ApiRequest {
        this.actionsList(teamId)
        this.pathComponents.push(actionId.toString())
        return this
    }

    // Request finalization

    public async get(options?: { signal?: AbortSignal }): Promise<any> {
        const url = this.assembleFullUrl()
        return await api.get(url, options?.signal)
    }

    public async update(options?: { data: any }): Promise<any> {
        const url = this.assembleFullUrl()
        return await api.update(url, options?.data)
    }

    public async create(options?: { data: any }): Promise<any> {
        const url = this.assembleFullUrl()
        return await api.create(url, options?.data)
    }

    public async delete(): Promise<any> {
        const url = this.assembleFullUrl()
        return await api.delete(url)
    }
}

class Api extends Function {
    // @ts-expect-error - we DON'T need or want to call super() here
    constructor() {
        function createApiRequest(): ApiRequest {
            return new ApiRequest()
        }
        Object.setPrototypeOf(createApiRequest, Api.prototype)
        // @ts-expect-error - this DOES in reality match the expected constructor signature
        return createApiRequest
    }

    public async get(url: string, signal?: AbortSignal): Promise<any> {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }

        let response
        const startTime = new Date().getTime()
        try {
            response = await fetch(url, { signal })
        } catch (e) {
            throw { status: 0, message: e }
        }

        if (!response.ok) {
            reportError('GET', url, response, startTime)
            const data = await getJSONOrThrow(response)
            throw { status: response.status, ...data }
        }
        return await getJSONOrThrow(response)
    }

    public async update(url: string, data: any): Promise<any> {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const isFormData = data instanceof FormData
        const startTime = new Date().getTime()
        const response = await fetch(url, {
            method: 'PATCH',
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                'X-CSRFToken': getCookie('csrftoken') || '',
            },
            body: isFormData ? data : JSON.stringify(data),
        })
        if (!response.ok) {
            reportError('PATCH', url, response, startTime)
            const jsonData = await getJSONOrThrow(response)
            if (Array.isArray(jsonData)) {
                throw jsonData
            }
            throw { status: response.status, ...jsonData }
        }
        return await getJSONOrThrow(response)
    }

    public async create(url: string, data?: any): Promise<any> {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const isFormData = data instanceof FormData
        const startTime = new Date().getTime()
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                'X-CSRFToken': getCookie('csrftoken') || '',
            },
            body: data ? (isFormData ? data : JSON.stringify(data)) : undefined,
        })
        if (!response.ok) {
            reportError('POST', url, response, startTime)
            const jsonData = await getJSONOrThrow(response)
            if (Array.isArray(jsonData)) {
                throw jsonData
            }
            throw { status: response.status, ...jsonData }
        }
        return await getJSONOrThrow(response)
    }

    public async delete(url: string): Promise<any> {
        if (url.indexOf('http') !== 0) {
            url = '/' + url + (url.indexOf('?') === -1 && url[url.length - 1] !== '/' ? '/' : '')
        }
        const startTime = new Date().getTime()
        const response = await fetch(url, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCookie('csrftoken') || '',
            },
        })
        if (!response.ok) {
            reportError('DELETE', url, response, startTime)
            const data = await getJSONOrThrow(response)
            throw { status: response.status, ...data }
        }
        return response
    }
}

interface Api {
    (): ApiRequest
}

function reportError(method: string, url: string, response: Response, startTime: number): void {
    const duration = new Date().getTime() - startTime
    const pathname = new URL(url, location.origin).pathname
    posthog.capture('client_request_failure', { pathname, method, duration, status: response.status })
}

const api = new Api()
export default api
