export type NotebookDataframeResult = {
    columns: string[]
    rows: Record<string, any>[]
    rowCount: number
}

export type PythonKernelVariableResponse = {
    status: 'ok' | 'error'
    data?: Record<string, any>
    metadata?: Record<string, any>
    type?: string
    hogql_query?: string | null
    ename?: string
    evalue?: string
    traceback?: string[]
}

export type PythonKernelExecuteResponse = {
    status: string
    stdout: string
    stderr: string
    result?: Record<string, any> | null
    media?: { mime_type: string; data: string }[] | null
    execution_count?: number | null
    error_name?: string | null
    traceback?: string[]
    variables?: Record<string, PythonKernelVariableResponse> | null
    started_at?: string
    completed_at?: string
    kernel_runtime?: {
        id: string
        status: string
        last_used_at?: string | null
        sandbox_id?: string | null
    }
}
