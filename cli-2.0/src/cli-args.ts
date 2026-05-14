const INTERNAL_COMMAND_PARAM_KEYS = new Set(['_', '$0', 'mcpContext', 'json', 'projectId', 'project-id'])

export function getProjectIdOverride(argv: Record<string, unknown>): string | undefined {
    const rawProjectId = argv.projectId ?? argv['project-id']
    if (typeof rawProjectId !== 'string') {
        return undefined
    }

    const projectId = rawProjectId.trim()
    return projectId.length > 0 ? projectId : undefined
}

export function buildCommandParams(argv: Record<string, unknown>): Record<string, unknown> {
    const params: Record<string, unknown> = {}

    for (const [key, value] of Object.entries(argv)) {
        if (!INTERNAL_COMMAND_PARAM_KEYS.has(key)) {
            params[key] = value
        }
    }

    return params
}
