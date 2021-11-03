import posthog from 'posthog-js'
import { parsePeopleParams, PeopleParamType } from '../scenes/trends/personsModalLogic'
import { ActionType, CohortType, FilterType, PersonType, PluginLogEntry, TeamType } from '../types'
import { getCurrentTeamId } from './utils/logics'
import { CheckboxValueType } from 'antd/lib/checkbox/Group'
import { LOGS_PORTION_LIMIT } from 'scenes/plugins/plugin/pluginLogsLogic'
import { toParams } from 'lib/utils'

export interface PaginatedResponse<T> {
    results: T[]
    next?: string
    previous?: string
}

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

    // Generic endpoint composition

    private addPathComponent(component: string): ApiRequest {
        this.pathComponents.push(component)
        return this
    }

    public withQueryString(queryString?: string): ApiRequest {
        this.queryString = queryString
        return this
    }

    public withAction(apiAction: string): ApiRequest {
        return this.addPathComponent(apiAction)
    }

    // API-aware endpoint composition

    public projects(): ApiRequest {
        return this.addPathComponent('projects')
    }

    public projectsDetail(id: TeamType['id'] = getCurrentTeamId()): ApiRequest {
        return this.projects().addPathComponent(id.toString())
    }

    public pluginLogs(pluginConfigId: number): ApiRequest {
        return this.addPathComponent('plugin_configs')
            .addPathComponent(pluginConfigId.toString())
            .addPathComponent('logs')
    }

    public actions(teamId: TeamType['id'] = getCurrentTeamId()): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('actions')
    }

    public actionsDetail(actionId: ActionType['id'], teamId: TeamType['id'] = getCurrentTeamId()): ApiRequest {
        return this.actions(teamId).addPathComponent(actionId.toString())
    }

    public cohorts(teamId: TeamType['id'] = getCurrentTeamId()): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('cohorts')
    }

    public cohortsDetail(cohortId: CohortType['id'], teamId: TeamType['id'] = getCurrentTeamId()): ApiRequest {
        return this.cohorts(teamId).addPathComponent(cohortId.toString())
    }

    // Request finalization

    public async get(options?: { signal?: AbortSignal }): Promise<any> {
        return await api.get(this.assembleFullUrl(), options?.signal)
    }

    public async update(options?: { data: any }): Promise<any> {
        return await api.update(this.assembleFullUrl(), options?.data)
    }

    public async create(options?: { data: any }): Promise<any> {
        return await api.create(this.assembleFullUrl(), options?.data)
    }

    public async delete(): Promise<any> {
        return await api.delete(this.assembleFullUrl())
    }
}

const api = {
    actions: {
        async get(actionId: ActionType['id']): Promise<ActionType> {
            return await new ApiRequest().actionsDetail(actionId).get()
        },
        async create(actionData: Partial<ActionType>, temporaryToken?: string): Promise<ActionType> {
            return await new ApiRequest()
                .actions()
                .withQueryString(temporaryToken ? `temporary_token=${temporaryToken}` : '')
                .create({ data: actionData })
        },
        async update(
            actionId: ActionType['id'],
            actionData: Partial<ActionType>,
            temporaryToken?: string
        ): Promise<ActionType> {
            return await new ApiRequest()
                .actionsDetail(actionId)
                .withQueryString(temporaryToken ? `temporary_token=${temporaryToken}` : '')
                .update({ data: actionData })
        },
        async list(params?: string): Promise<PaginatedResponse<ActionType>> {
            return await new ApiRequest().actions().withQueryString(params).get()
        },
        async getPeople(
            peopleParams: PeopleParamType,
            filters: Partial<FilterType>,
            searchTerm?: string
        ): Promise<PaginatedResponse<{ people: PersonType[]; count: number }>> {
            return await new ApiRequest()
                .actions()
                .withAction('people')
                .withQueryString(
                    parsePeopleParams(peopleParams, filters) +
                        (searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : '')
                )
                .get()
        },
        async getCount(actionId: ActionType['id']): Promise<number> {
            return (await new ApiRequest().actionsDetail(actionId).withAction('count').get()).count
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().actions().assembleEndpointUrl()
        },
        determinePeopleCsvUrl(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
            return new ApiRequest()
                .actions()
                .withAction('people.csv')
                .withQueryString(parsePeopleParams(peopleParams, filters))
                .assembleFullUrl(true)
        },
    },

    cohorts: {
        async get(cohortId: CohortType['id']): Promise<CohortType> {
            return await new ApiRequest().cohortsDetail(cohortId).get()
        },
        async create(cohortData: Partial<CohortType>, filterParams?: string): Promise<CohortType> {
            return await new ApiRequest().cohorts().withQueryString(filterParams).create({ data: cohortData })
        },
        async update(
            cohortId: CohortType['id'],
            cohortData: Partial<CohortType>,
            filterParams?: string
        ): Promise<CohortType> {
            return await new ApiRequest()
                .cohortsDetail(cohortId)
                .withQueryString(filterParams)
                .update({ data: cohortData })
        },
        async list(): Promise<PaginatedResponse<CohortType>> {
            return await new ApiRequest().cohorts().get()
        },
        determineDeleteEndpoint(): string {
            return new ApiRequest().cohorts().assembleEndpointUrl()
        },
    },

    pluginLogs: {
        async search(
            pluginConfigId: number,
            currentTeamId: number | null,
            searchTerm: string | null = null,
            typeFilters: CheckboxValueType[] = [],
            trailingEntry: PluginLogEntry | null = null,
            leadingEntry: PluginLogEntry | null = null
        ): Promise<PluginLogEntry[]> {
            const params = toParams(
                {
                    limit: LOGS_PORTION_LIMIT,
                    type_filter: typeFilters,
                    search: searchTerm || undefined,
                    before: trailingEntry?.timestamp,
                    after: leadingEntry?.timestamp,
                },
                true
            )

            const response = await new ApiRequest()
                .projectsDetail(currentTeamId || undefined)
                .pluginLogs(pluginConfigId)
                .withQueryString(params)
                .get()

            return response.results
        },
    },

    async get(url: string, signal?: AbortSignal): Promise<any> {
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
    },

    async update(url: string, data: any): Promise<any> {
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
    },

    async create(url: string, data?: any): Promise<any> {
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
    },

    async delete(url: string): Promise<any> {
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
    },
}

function reportError(method: string, url: string, response: Response, startTime: number): void {
    const duration = new Date().getTime() - startTime
    const pathname = new URL(url, location.origin).pathname
    posthog.capture('client_request_failure', { pathname, method, duration, status: response.status })
}

export default api
