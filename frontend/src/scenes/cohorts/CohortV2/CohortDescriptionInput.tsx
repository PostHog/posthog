import React from 'react'
import { Input } from 'antd'
import './cohort.scss'

interface CohortDescriptionInputProps {
    description?: string
    onChange: (input: string) => void
}

export function CohortDescriptionInput({ description, onChange }: CohortDescriptionInputProps): JSX.Element {
    return (
        <>
            <span className="sub-header">Description</span>
            <Input.TextArea
                required
                autoFocus
                placeholder="Add a useful description for other team members"
                value={description || ''}
                data-attr="cohort-name"
                onChange={(e) => onChange(e.target.value)}
                autoSize={{ minRows: 2, maxRows: 4 }}
            />
        </>
    )
}
