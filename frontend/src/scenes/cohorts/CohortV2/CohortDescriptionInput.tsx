import React from 'react'
import { Input } from 'antd'

interface CohortDescriptionInputProps {
    description?: string
    onChange: (input: string) => void
}

export function CohortDescriptionInput({ description, onChange }: CohortDescriptionInputProps): JSX.Element {
    return (
        <>
            <label className="ant-form-item-label" htmlFor="cohort-description">
                Description
            </label>
            <Input.TextArea
                placeholder="Add a useful description for other team members"
                value={description || ''}
                data-attr="cohort-description"
                id="cohort-description"
                onChange={(e) => onChange(e.target.value)}
            />
        </>
    )
}
