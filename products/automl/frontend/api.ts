import api from 'lib/api'

// Hand-written response shapes — keep in sync with products/automl/backend/serializers.py
// until `hogli build:openapi` is wired up for this product.

export interface RunSummary {
    id: string
    shipped: boolean
    is_current: boolean
    manifest: Record<string, unknown> | null
}

export interface TaskSummary {
    name: string
    has_spec: boolean
    spec: Record<string, unknown> | null
    current_query_version: string | null
    current_run_id: string | null
    current_run_manifest: Record<string, unknown> | null
    run_count: number
}

export interface TaskDetail {
    name: string
    spec: Record<string, unknown> | null
    spec_raw: string | null
    queries: string[]
    current_query_version: string | null
    runs: RunSummary[]
    current_run_id: string | null
}

export interface RunDetail {
    task_name: string
    id: string
    manifest: Record<string, unknown> | null
    manifest_raw: string | null
    artifacts: string[]
    is_current: boolean
}

export interface QueryText {
    task_name: string
    version: string
    sql: string
}

export interface ParquetPreview {
    columns: string[]
    rows: Record<string, unknown>[]
    total_rows: number
    returned_rows: number
    offset: number
}

function base(): string {
    return `/api/automl/tasks`
}

export async function listTasks(): Promise<TaskSummary[]> {
    return await api.get<TaskSummary[]>(`${base()}/`)
}

export async function getTask(name: string): Promise<TaskDetail> {
    return await api.get<TaskDetail>(`${base()}/${encodeURIComponent(name)}/`)
}

export async function getQuery(name: string, version: string): Promise<QueryText> {
    return await api.get<QueryText>(`${base()}/${encodeURIComponent(name)}/queries/${encodeURIComponent(version)}/`)
}

export async function getRun(name: string, runId: string): Promise<RunDetail> {
    return await api.get<RunDetail>(`${base()}/${encodeURIComponent(name)}/runs/${encodeURIComponent(runId)}/`)
}

export async function previewParquet(
    name: string,
    runId: string,
    artifact: string = 'predictions.parquet',
    limit: number = 25,
    offset: number = 0
): Promise<ParquetPreview> {
    const params = new URLSearchParams({ artifact, limit: String(limit), offset: String(offset) })
    return await api.get<ParquetPreview>(
        `${base()}/${encodeURIComponent(name)}/runs/${encodeURIComponent(runId)}/preview/?${params.toString()}`
    )
}
