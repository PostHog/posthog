import { useRef } from 'react'

/**
 * Browser/password-manager autofill of a controlled input doesn't always reach kea form state:
 * when the form is rendered after an async step (e.g. invite prevalidation) the field appears too
 * late for the fill to fire a React onChange, so the input shows masked characters while form
 * state stays empty and validation blocks the submit. Read the live DOM values on submit and push
 * them into form state before validation runs.
 *
 * Attach the returned `fieldRef(name)` to each autofillable input's `inputRef`, and call
 * `reconcile(setValue)` from the form's `onSubmitCapture` — the capture phase commits the values
 * synchronously before kea-forms validates on the bubbling `onSubmit`.
 */
export function useAutofillReconcile(): {
    fieldRef: (name: string) => (el: HTMLInputElement | null) => void
    reconcile: (setValue: (name: string, value: string) => void) => void
} {
    const refs = useRef<Record<string, HTMLInputElement | null>>({})

    const fieldRef =
        (name: string) =>
        (el: HTMLInputElement | null): void => {
            refs.current[name] = el
        }

    const reconcile = (setValue: (name: string, value: string) => void): void => {
        for (const [name, el] of Object.entries(refs.current)) {
            const domValue = el?.value
            // Only sync a non-empty value the form doesn't have yet; never clobber an empty field,
            // so genuinely blank inputs still surface their validation error.
            if (domValue) {
                setValue(name, domValue)
            }
        }
    }

    return { fieldRef, reconcile }
}
