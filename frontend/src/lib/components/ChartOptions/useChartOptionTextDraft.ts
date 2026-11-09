import { useEffect, useState } from 'react'

export function useChartOptionTextDraft(
    value: string | undefined,
    onChange: (value: string | undefined) => void
): { draft: string; setDraft: (draft: string) => void; commit: () => void } {
    const [draft, setDraft] = useState(value ?? '')

    useEffect(() => {
        setDraft(value ?? '')
    }, [value])

    const commit = (): void => {
        const trimmed = draft.trim()
        setDraft(trimmed)
        onChange(trimmed || undefined)
    }

    return { draft, setDraft, commit }
}
