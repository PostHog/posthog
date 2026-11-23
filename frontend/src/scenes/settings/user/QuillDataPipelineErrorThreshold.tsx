import {
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
} from '@posthog/quill'

import { DATA_PIPELINE_THRESHOLD_DESCRIPTION } from './emailPreferencesCopy'

export function QuillDataPipelineErrorThreshold({
    value,
    onChange,
    error,
    disabled,
}: {
    value: number
    onChange: (value: number | undefined) => void
    error?: string
    disabled: boolean
}): JSX.Element {
    return (
        <Field data-invalid={error ? true : undefined} className="ps-9">
            <FieldLabel htmlFor="data-pipeline-error-threshold">Failure rate threshold</FieldLabel>
            <InputGroup className="w-32">
                <InputGroupInput
                    id="data-pipeline-error-threshold"
                    type="number"
                    min={0}
                    max={100}
                    step={0.1}
                    value={value}
                    onChange={(event) => onChange(event.target.valueAsNumber)}
                    disabled={disabled}
                    aria-invalid={error ? true : undefined}
                />
                <InputGroupAddon align="inline-end">%</InputGroupAddon>
            </InputGroup>
            <FieldDescription>{DATA_PIPELINE_THRESHOLD_DESCRIPTION}</FieldDescription>
            {error && <FieldError>{error}</FieldError>}
        </Field>
    )
}
