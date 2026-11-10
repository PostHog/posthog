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
