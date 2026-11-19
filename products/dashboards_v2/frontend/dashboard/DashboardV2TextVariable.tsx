import { useEffect, useState } from 'react'

import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill'

interface DashboardV2TextVariableProps {
    label: string
    value: string
    onChange: (value: string) => void
}

export function DashboardV2TextVariable({ label, value, onChange }: DashboardV2TextVariableProps): JSX.Element {
    const [draft, setDraft] = useState(value)

    useEffect(() => {
        setDraft(value)
    }, [value])

    const commit = (): void => {
        if (draft !== value) {
            onChange(draft)
        }
    }

    return (
        <InputGroup size="sm" className="w-56">
            <InputGroupAddon>
                <InputGroupText>{label}</InputGroupText>
            </InputGroupAddon>
            <InputGroupInput
                aria-label={label}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                        commit()
                    }
                }}
                data-attr="dashboard-v2-variable-text"
            />
        </InputGroup>
    )
}
