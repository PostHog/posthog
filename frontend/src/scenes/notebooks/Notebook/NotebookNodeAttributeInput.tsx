import { useCallback, useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput } from '@posthog/lemon-ui'

import { isUUIDLike } from 'lib/utils/guards'

export const NOTEBOOK_NODE_ATTRIBUTE_COMMIT_DEBOUNCE_MS = 400

/**
 * Committing straight through on every keystroke re-runs the node's backend query per character,
 * and each half-typed value comes back a 400 with its own error toast. So hold the keystrokes
 * locally, commit on a pause or on blur, and never commit a half-typed UUID at all.
 */
export function NotebookNodeAttributeInput({
    label,
    value,
    expectsUUID,
    onCommit,
    autoFocus,
}: {
    label: string
    value: string
    expectsUUID: boolean
    onCommit: (value: string) => void
    autoFocus?: boolean
}): JSX.Element {
    const [draft, setDraft] = useState(value)
    const committedRef = useRef(value)

    // An edit landing from elsewhere (undo, a collaborator) should win over an untouched draft.
    // The parent stores attributes trimmed, so its echo of what we just sent is not such an edit —
    // resetting on it would eat a space the moment you typed one.
    useEffect(() => {
        if (value !== committedRef.current && value.trim() !== draft.trim()) {
            committedRef.current = value
            setDraft(value)
        }
    }, [value, draft])

    const commit = useCallback(
        (raw: string) => {
            const next = expectsUUID ? raw.trim() : raw
            if (next === committedRef.current || (expectsUUID && !!next && !isUUIDLike(next))) {
                return
            }
            committedRef.current = next
            onCommit(next)
        },
        [expectsUUID, onCommit]
    )

    const commitDebounced = useDebouncedCallback(commit, NOTEBOOK_NODE_ATTRIBUTE_COMMIT_DEBOUNCE_MS)

    // Collapsing the node or closing the settings panel can unmount us without a blur, and the
    // pending commit would go with it. Flush it so a typed value is never silently dropped.
    useEffect(() => () => commitDebounced.flush(), [commitDebounced])

    const showUUIDHint = expectsUUID && !!draft.trim() && !isUUIDLike(draft.trim())

    return (
        <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-secondary">{label}</span>
            <LemonInput
                aria-label={label}
                value={draft}
                onChange={(next) => {
                    setDraft(next)
                    commitDebounced(next)
                }}
                onBlur={() => {
                    commitDebounced.cancel()
                    commit(draft)
                }}
                placeholder={label}
                autoFocus={autoFocus}
            />
            {showUUIDHint && (
                <span className="text-xs text-secondary">
                    Enter a full UUID, like 0198a4c2-8b3d-7e50-b4a1-2f9c6d8e0a1b
                </span>
            )}
        </label>
    )
}
