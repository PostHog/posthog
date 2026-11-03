import { useState } from 'react'

import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { METRIC_FIELD_COPY } from '../common'

const UNIT_INPUT_ID = 'data-catalog-metric-unit'

export function QuillMetricUnitEditor({ unit, onSave }: { unit: string; onSave: (unit: string) => void }): JSX.Element {
    const [value, setValue] = useState(unit)

    return (
        <Field className="max-w-md">
            <FieldLabel htmlFor={UNIT_INPUT_ID}>{METRIC_FIELD_COPY.unit.label}</FieldLabel>
            <div className="flex items-center gap-2">
                <Input
                    id={UNIT_INPUT_ID}
                    size="sm"
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder={METRIC_FIELD_COPY.unit.placeholder}
                />
                <Button
                    variant="outline"
                    disabledReason={value === unit ? 'No changes to save' : undefined}
                    onClick={() => onSave(value)}
                >
                    Save
                </Button>
            </div>
            <FieldDescription>How the result is measured, like users, dollars, or percent.</FieldDescription>
        </Field>
    )
}
