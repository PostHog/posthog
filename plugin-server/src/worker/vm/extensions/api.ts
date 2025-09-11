import { Hub, PluginConfig } from '../../../types'
import { Response, legacyFetch } from '../../../utils/request'

const DEFAULT_API_HOST = 'https://app.posthog.com'

interface ApiMethodOptions {
    headers?: Headers
    data?: Record<string, any>
    host?: string
    projectApiKey?: string
    personalApiKey?: string
}

export interface ApiExtension {
    get(path: string, options?: ApiMethodOptions): Promise<Response>
    post(path: string, options?: ApiMethodOptions): Promise<Response>
    put(path: string, options?: ApiMethodOptions): Promise<Response>
    patch(path: string, options?: ApiMethodOptions): Promise<Response>
    delete(path: string, options?: ApiMethodOptions): Promise<Response>
}

enum ApiMethod {
    Get = 'GET',
    Post = 'POST',
    Put = 'PUT',
    Patch = 'PATCH',
    Delete = 'DELETE',
}

export function createApi(server: Hub, pluginConfig: PluginConfig): ApiExtension {
    const sendRequest = async (path: string, method: ApiMethod, options?: ApiMethodOptions): Promise<Response> => {
        options = options ?? ({} as ApiMethodOptions)

        // NOR operation: it's fine if personalApiKey and projectApiKey both are set or unset,
        // but it's not fine if one is set if the other isn't
        if (!!options.personalApiKey !== !!options.projectApiKey) {
            throw new Error('You must specify a personalApiKey if you specify a projectApiKey and vice-versa!')
        }

        let host = options.host ?? process.env.SITE_URL ?? DEFAULT_API_HOST

        if (path.startsWith('/')) {
            path = path.slice(1)
        }
        if (host.endsWith('/')) {
            host = host.slice(0, host.length - 1)
        }

        const tokenParam: Record<string, string> = { token: '' }
        let apiKey = options.personalApiKey

        if (options.projectApiKey) {
            tokenParam.token = options.projectApiKey
        } else {
            const team = await server.teamManager.getTeam(pluginConfig.team_id)
            if (!team) {
                throw new Error('Unable to determine project')
            }

            tokenParam['token'] = team.api_token
            apiKey = await server.pluginsApiKeyManager.fetchOrCreatePersonalApiKey(team.organization_id)
        }

        const urlParams = new URLSearchParams(
            method === (ApiMethod.Get || ApiMethod.Delete) && options && options.data
                ? { ...options.data, ...tokenParam }
                : tokenParam
        )
        const url = `${host}/${path.replace('@current', pluginConfig.team_id.toString())}${
            path.includes('?') ? '&' : '?'
        }${urlParams.toString()}`

        const headers = {
            Authorization: `Bearer ${apiKey}`,
            ...(method === ApiMethod.Post || method === ApiMethod.Patch ? { 'Content-Type': 'application/json' } : {}),
            ...options.headers,
        } as any

        if (method === ApiMethod.Delete || method === ApiMethod.Get) {
            return await legacyFetch(url, { headers, method })
        }

        return await legacyFetch(url, { headers, method, body: JSON.stringify(options.data || {}) })
    }

    return {
        get: async (path, options) => {
            return await sendRequest(path, ApiMethod.Get, options)
        },
        post: async (path, options) => {
            return await sendRequest(path, ApiMethod.Post, options)
        },
        put: async (path, options) => {
            return await sendRequest(path, ApiMethod.Put, options)
        },
        patch: async (path, options) => {
            return await sendRequest(path, ApiMethod.Patch, options)
        },
        delete: async (path, options) => {
            return await sendRequest(path, ApiMethod.Delete, options)
        },
    }
}
