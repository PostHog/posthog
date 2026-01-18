export type PythonExecutionVariableStatus = 'ok' | 'error' | 'missing'

export type PythonExecutionVariable = {
    name: string
    type: string
    status: PythonExecutionVariableStatus
    value?: string
    error?: string
    traceback?: string[]
}

export type PythonExecutionMedia = {
    mimeType: string
    data: string
}

export type PythonExecutionResult = {
    status: string
    stdout: string
    stderr: string
    result?: string
    executionCount?: number | null
    errorName?: string | null
    traceback?: string[]
    variables?: PythonExecutionVariable[]
    media?: PythonExecutionMedia[]
    startedAt?: string
    completedAt?: string
}

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

const extractTextValue = (data?: Record<string, any> | null): string | undefined => {
    if (!data) {
        return undefined
    }

    const preferred = data['text/plain'] ?? data['text/html']
    if (typeof preferred === 'string') {
        return preferred
    }

    const imageMimeTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/svg+xml', 'image/gif', 'image/webp']

    if (imageMimeTypes.some((mimeType) => data[mimeType])) {
        return undefined
    }

    try {
        return JSON.stringify(data)
    } catch {
        return undefined
    }
}

const formatExecutionError = (ename?: string | null, evalue?: string | null): string | undefined => {
    if (!ename && !evalue) {
        return undefined
    }
    if (!ename) {
        return evalue ?? undefined
    }
    if (!evalue) {
        return ename
    }
    return `${ename}: ${evalue}`
}

export const mergeExecutionVariables = (
    exportedGlobals: { name: string; type: string }[],
    variables?: Record<string, PythonKernelVariableResponse> | null
): PythonExecutionVariable[] => {
    return exportedGlobals.map(({ name, type }) => {
        const variable = variables?.[name]
        const resolvedType = variable?.type ?? type
        if (!variable) {
            return {
                name,
                type: resolvedType,
                status: 'missing',
            }
        }
        if (variable.status === 'error') {
            return {
                name,
                type: resolvedType,
                status: 'error',
                error: formatExecutionError(variable.ename, variable.evalue),
                traceback: variable.traceback ?? [],
            }
        }
        return {
            name,
            type: resolvedType,
            status: 'ok',
            value: extractTextValue(variable.data),
        }
    })
}

export const buildPythonExecutionResult = (
    response: PythonKernelExecuteResponse,
    exportedGlobals: { name: string; type: string }[]
): PythonExecutionResult => {
    return {
        status: response.status,
        stdout: response.stdout ?? '',
        stderr: response.stderr ?? '',
        result: extractTextValue(response.result ?? undefined),
        media: response.media?.map((item) => ({ mimeType: item.mime_type, data: item.data })) ?? [],
        executionCount: response.execution_count ?? null,
        errorName: response.error_name ?? null,
        traceback: response.traceback ?? [],
        variables: mergeExecutionVariables(exportedGlobals, response.variables ?? undefined),
        startedAt: response.started_at,
        completedAt: response.completed_at,
    }
}

export const buildPythonExecutionError = (
    message: string,
    exportedGlobals: { name: string; type: string }[]
): PythonExecutionResult => {
    return {
        status: 'error',
        stdout: '',
        stderr: '',
        errorName: 'RuntimeError',
        traceback: [message],
        variables: mergeExecutionVariables(exportedGlobals, {}),
    }
}
