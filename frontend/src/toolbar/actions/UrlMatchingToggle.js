import React from 'react'
import { Button } from 'antd'

export function UrlMatchingToggle({ value, onChange, style }) {
    return (
        <Button.Group size="small" style={style}>
            <Button type={value === 'contains' ? 'primary' : 'outline'} onClick={() => onChange('contains')}>
                Contains
            </Button>
            <Button type={value === 'exact' ? 'primary' : 'outline'} onClick={() => onChange('exact')}>
                Exactly Matches
            </Button>
        </Button.Group>
    )
}
