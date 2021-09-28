import React from 'react'
import { Input } from 'antd'

interface CohortNameInputProps {
    input?: string
    onChange: (input: string) => void
}

export function CohortNameInput({ input, onChange }: CohortNameInputProps): JSX.Element {
    return (
        <>
            <label className="ant-form-item-label" htmlFor="cohort-name">
                Name
            </label>
            <Input
                required
                autoFocus
                placeholder="Name your cohort"
                value={input || ''}
                data-attr="cohort-name"
                onChange={(e) => onChange(e.target.value)}
                id="cohort-name"
                className="ph-ignore-input"
            />
        </>
    )
}
