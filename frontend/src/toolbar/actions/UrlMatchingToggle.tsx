import { Button } from 'antd'
import { ActionStepType, ActionStepUrlMatching } from '~/types'

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
                onClick={() => onChange && onChange(ActionStepUrlMatching.Contains)}
            >
                Contains
            </Button>
            <Button
                type={value === 'regex' ? 'primary' : 'default'}
                onClick={() => onChange && onChange(ActionStepUrlMatching.Regex)}
            >
                Regex
            </Button>
            <Button
                type={value === 'exact' ? 'primary' : 'default'}
                onClick={() => onChange && onChange(ActionStepUrlMatching.Exact)}
            >
                Exact match
            </Button>
        </Button.Group>
    )
}
