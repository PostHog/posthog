import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

/**
 * kea-forms hands only the client-side validation errors to the fields, so a submit failure listener
 * calls this to show the server's message: under the field it names, or as a toast when it names none.
 */
export function showServerFormError(
    error: unknown,
    formValues: Record<string, unknown>,
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
