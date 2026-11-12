import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

/** kea-forms hands only client-side errors to the fields, so a submit failure listener calls this for the server's. */
export function showServerFormError(
    error: unknown,
    formValues: object,
    setManualErrors: (errors: Record<string, string>) => void,
    fallbackMessage: string
): void {
    if (!(error instanceof ApiError)) {
        return
    }
    if (error.attr && error.attr in formValues) {
        setManualErrors({ [error.attr]: error.detail || error.message })
    } else {
        lemonToast.error(error.detail || fallbackMessage)
    }
}

/** kea-forms drops a manual error only on blur, and a stale one blocks a resubmit from the Enter key. */
export function clearManualError(
    key: string | number,
    manualErrors: Record<string, unknown>,
    setManualErrors: (errors: Record<string, unknown>) => void
): void {
    if (!(key in manualErrors)) {
        return
    }
    const { [key]: _stale, ...remainingErrors } = manualErrors
    setManualErrors(remainingErrors)
}
