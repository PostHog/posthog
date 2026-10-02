export interface SaveAsDisabledReasonInput {
    insightLoading: boolean
    isSourceQueryLastRun: boolean
    responseLoading: boolean
    responseError: unknown
    response: unknown
}

export function getSaveAsDisabledReason({
    insightLoading,
    isSourceQueryLastRun,
    responseLoading,
    responseError,
    response,
}: SaveAsDisabledReasonInput): string | undefined {
    if (insightLoading) {
        return 'Loading insight...'
    }

    if (!isSourceQueryLastRun) {
        return 'Run latest query changes before saving'
    }

    if (responseLoading) {
        return 'Running query...'
    }

    if (responseError || !response) {
        return 'Run query successfully before saving'
    }

    return undefined
}
