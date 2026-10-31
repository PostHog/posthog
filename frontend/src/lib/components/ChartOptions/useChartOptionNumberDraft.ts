import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

// A number input reads as empty mid-entry, so only a finite value is sent while typing; a field
// left empty clears the setting when it loses focus.
export function useChartOptionNumberDraft(
    value: number | undefined,
    onChange: (value: number | undefined) => void
): { draft: number | undefined; setDraft: (draft: number | undefined) => void; commit: () => void } {
    const [draft, setDraftState] = useState(value)

    useEffect(() => {
        setDraftState(value)
    }, [value])

    const sendWhileTyping = useDebouncedCallback((next: number) => onChange(next), 300)

    const setDraft = (next: number | undefined): void => {
        setDraftState(next)
        if (typeof next === 'number' && Number.isFinite(next)) {
            sendWhileTyping(next)
        }
    }

    const commit = (): void => {
        sendWhileTyping.cancel()
        const finite = typeof draft === 'number' && Number.isFinite(draft) ? draft : undefined
        if (finite !== value) {
            onChange(finite)
        }
    }

    return { draft, setDraft, commit }
}
