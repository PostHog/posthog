import { useEffect, useId, useState } from 'react'

export interface NameErrorTooltip {
    open: boolean
    onOpenChange: (open: boolean) => void
    errorId: string
    inputProps: {
        'aria-invalid': true | undefined
        'aria-describedby': string | undefined
        onFocus: () => void
        onBlur: () => void
    }
}

/** Opens the error tooltip on hover and while the field has focus, and lets Escape close it. */
export function useNameErrorTooltip(error: string | undefined, fieldOpen: boolean): NameErrorTooltip {
    const [open, setOpen] = useState(false)
    const errorId = useId()
    // A field that unmounts while focused fires no blur, so the tooltip would otherwise reopen on its own later.
    useEffect(() => {
        if (!fieldOpen) {
            setOpen(false)
        }
    }, [fieldOpen])
    const hasError = !!error
    return {
        open: hasError && open,
        onOpenChange: setOpen,
        errorId,
        inputProps: {
            'aria-invalid': hasError || undefined,
            'aria-describedby': hasError ? errorId : undefined,
            onFocus: () => setOpen(true),
            onBlur: () => setOpen(false),
        },
    }
}
