import React from 'react'
import { Input, Col } from 'antd'
import './cohort.scss'

interface CohortNameInputProps {
    input?: string
    onChange: (input: string) => void
}

export function CohortNameInput({ input, onChange }: CohortNameInputProps): JSX.Element {
    return (
        <Col>
            <span className="header">Name</span>
            <Input
                required
                autoFocus
                placeholder="Cohort name..."
                value={input || ''}
                data-attr="cohort-name"
                onChange={(e) => onChange(e.target.value)}
            />
        </Col>
    )
}
