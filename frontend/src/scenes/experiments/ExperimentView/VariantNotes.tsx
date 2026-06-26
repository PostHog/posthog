import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconPencil } from '@posthog/icons'

import { experimentLogic } from '../experimentLogic'

// Shared box model so the display div and the edit textarea have identical
// dimensions — switching between them causes no layout shift.
const BOX = 'h-20 w-full p-2 rounded border text-sm overflow-auto'

export function VariantNotes({ variantKey }: { variantKey: string }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperimentVariantNotes } = useActions(experimentLogic)

    const note = experiment.parameters?.variant_notes?.[variantKey] ?? ''
    const [isEditing, setIsEditing] = useState(false)
    const [draft, setDraft] = useState(note)

    const handleSave = (): void => {
        if (draft !== note) {
            updateExperimentVariantNotes({
                ...experiment.parameters?.variant_notes,
                [variantKey]: draft,
            })
        }
        setIsEditing(false)
    }

    if (isEditing) {
        return (
            <div className="relative my-2">
                <textarea
                    className={`${BOX} block border-solid border-primary resize-none focus:outline-none`}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={handleSave}
                    onFocus={(e) => e.target.setSelectionRange(e.target.value.length, e.target.value.length)}
                    autoFocus
                />
                <button
                    type="button"
                    aria-label="Save notes"
                    className="absolute bottom-1 right-1 flex p-1 rounded text-base text-secondary hover:text-primary hover:bg-fill-button-tertiary-hover cursor-pointer"
                    // Keep focus on the textarea so onBlur doesn't fire and unmount us before onClick.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={handleSave}
                >
                    <IconCheck />
                </button>
            </div>
        )
    }

    return (
        <div
            className={`${BOX} relative my-2 border-dashed border-border hover:border-primary cursor-text whitespace-pre-wrap break-words`}
            onClick={() => {
                setDraft(note)
                setIsEditing(true)
            }}
        >
            <span className="pr-5">{note}</span>
            <IconPencil className="absolute top-1 right-1 text-muted opacity-50" />
        </div>
    )
}
