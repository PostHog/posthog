import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

const toText = (value: number | undefined): string => (value === undefined ? '' : String(value))

export const parseChartOptionNumber = (text: string): number | undefined => {
    if (text.trim() === '') {
        return undefined
    }
    const parsed = Number(text)
    return Number.isFinite(parsed) ? parsed : undefined
}

// The draft stays raw text, so partial entries like "-" or "1." survive until they parse. Only a
// finite value is sent while typing; a field left empty clears the setting when it loses focus.
export function useChartOptionNumberDraft(
    value: number | undefined,
    onChange: (value: number | undefined) => void
): { draft: string; setDraft: (draft: string) => void; commit: () => void } {
    const [draft, setDraftState] = useState(toText(value))

    useEffect(() => {
        setDraftState((current) => (parseChartOptionNumber(current) === value ? current : toText(value)))
    }, [value])

    const sendWhileTyping = useDebouncedCallback((next: number) => onChange(next), 300)

    const setDraft = (next: string): void => {
        setDraftState(next)
        const parsed = parseChartOptionNumber(next)
        if (parsed === undefined) {
            sendWhileTyping.cancel()
        } else {
            sendWhileTyping(parsed)
        }
    }

    const commit = (): void => {
        sendWhileTyping.cancel()
        const parsed = parseChartOptionNumber(draft)
        setDraftState(toText(parsed))
        if (parsed !== value) {
            onChange(parsed)
        }
    }

    return { draft, setDraft, commit }
}
