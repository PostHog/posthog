import React from 'react'
import { Button } from 'antd'
import { ActionStepType } from '~/types'

interface UrlMatchingToggleProps {
    value?: ActionStepType['url_matching']
    style: Record<string, any>
    onChange?: (urlMatching: ActionStepType['url_matching']) => void
}

export function UrlMatchingToggle({ value, onChange, style }: UrlMatchingToggleProps): JSX.Element {
    return (
        <Button.Group size="small" style={style}>
            <Button
                type={value === 'contains' ? 'primary' : 'default'}
                onClick={() => onChange && onChange('contains')}
            >
                Contains
            </Button>
            <Button type={value === 'regex' ? 'primary' : 'default'} onClick={() => onChange && onChange('regex')}>
                Regex
            </Button>
            <Button type={value === 'exact' ? 'primary' : 'default'} onClick={() => onChange && onChange('exact')}>
                Exact match
            </Button>
        </Button.Group>
    )
}
