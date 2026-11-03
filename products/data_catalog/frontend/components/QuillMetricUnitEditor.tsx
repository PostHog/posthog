import { useState } from 'react'

import { Button, Input } from '@posthog/quill'

import { METRIC_FIELD_COPY } from '../common'

export function QuillMetricUnitEditor({ unit, onSave }: { unit: string; onSave: (unit: string) => void }): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)

    if (draft === null) {
        return (
            <Button
                variant="default"
                size="sm"
                className="-ms-2"
                tooltip="How the result is measured, like users, dollars, or percent"
                onClick={() => setDraft(unit)}
                data-attr="data-catalog-metric-unit-edit"
            >
                {unit || 'Add a unit'}
            </Button>
        )
    }

    const save = (): void => {
        const next = draft.trim()
        setDraft(null)
        if (next !== unit) {
            onSave(next)
        }
    }

    return (
        <Input
            size="sm"
            className="w-40"
            autoFocus
            aria-label={METRIC_FIELD_COPY.unit.label}
            value={draft}
            placeholder={METRIC_FIELD_COPY.unit.placeholder}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={save}
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    save()
                }
                if (event.key === 'Escape') {
                    setDraft(null)
                }
            }}
            data-attr="data-catalog-metric-unit-input"
        />
    )
}
