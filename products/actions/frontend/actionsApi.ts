import { ApiConfig } from 'lib/api'

import type { ActionType } from '~/types'

import {
    actionsCreate,
    actionsList,
    actionsPartialUpdate,
    actionsReferencesList,
    actionsRetrieve,
    getActionsCreateUrl,
} from './generated/api'
import type { ActionReferenceApi, ActionsListParams } from './generated/api.schemas'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

const listParams = (query?: string): ActionsListParams => {
    const params = new URLSearchParams(query)
    const limit = params.get('limit')
    const offset = params.get('offset')
    return {
        created_by: params.get('created_by') ?? undefined,
        limit: limit === null ? undefined : Number(limit),
        offset: offset === null ? undefined : Number(offset),
        ordering: params.get('ordering') ?? undefined,
        search: params.get('search') ?? undefined,
        tags: params.get('tags') ?? undefined,
    }
}

export async function actionsListApi(query?: string): Promise<{ count: number; results: ActionType[] }> {
    const response = await actionsList(projectId(), listParams(query))
    return { count: response.count, results: response.results as unknown as ActionType[] }
}

export async function actionRetrieveApi(id: number): Promise<ActionType> {
    return (await actionsRetrieve(projectId(), id)) as unknown as ActionType
}

export async function actionCreateApi(data: Partial<ActionType>): Promise<ActionType> {
    return (await actionsCreate(projectId(), data as Parameters<typeof actionsCreate>[1])) as unknown as ActionType
}

export async function actionUpdateApi(id: number, data: Partial<ActionType>): Promise<ActionType> {
    return (await actionsPartialUpdate(
        projectId(),
        id,
        data as Parameters<typeof actionsPartialUpdate>[2]
    )) as unknown as ActionType
}

export async function actionReferencesApi(id: number): Promise<ActionReferenceApi[]> {
    return await actionsReferencesList(projectId(), id)
}

export const actionDeleteEndpoint = (): string =>
    getActionsCreateUrl(projectId())
        .replace(/^\/api\//, '')
        .replace(/\/$/, '')
