import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { sqlEditorLogic } from '../sqlEditorLogic'

export type FixErrorButtonSource = 'action-bar' | 'query-error'

export interface FixErrorButtonState {
    /** The error a fix would target, from the last run or from the editor's own checks. */
    queryError: string | undefined
    loading: boolean
    /** The last fix attempt failed, so the button reads "Can't fix". */
    failed: boolean
    disabledReason: string | undefined
    label: string
    fix: () => void
}

export function useFixErrorButtonState(source: FixErrorButtonSource, labelOverride?: string): FixErrorButtonState {
    const { queryInput, fixErrorsError, metadata, selectedConnectionId, fixErrorsLoading } = useValues(sqlEditorLogic)
    const { fixErrors } = useActions(sqlEditorLogic)
    const { responseError } = useValues(dataNodeLogic)

    const queryError = responseError || metadata?.errors?.map((n) => n.message)?.join('. ') || undefined

    return {
        queryError,
        loading: fixErrorsLoading,
        failed: !!fixErrorsError,
        disabledReason: !queryError ? 'No query error to fix' : fixErrorsError || undefined,
        label: fixErrorsLoading ? 'Fixing...' : fixErrorsError ? "Can't fix" : (labelOverride ?? 'Fix errors with AI'),
        fix: () => {
            fixErrors(queryInput ?? '', queryError, selectedConnectionId)
            posthog.capture(`sql-editor-fix-error-click`, { source })
        },
    }
}
