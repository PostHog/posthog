import { Radio } from 'antd'
import { StringMatching } from '~/types'

interface StringMatchingToggleProps {
    value?: StringMatching
    style: Record<string, any>
    onChange?: (urlMatching: StringMatching) => void
}

export function StringMatchingToggle({ value, onChange, style }: StringMatchingToggleProps): JSX.Element {
    return (
        <Radio.Group
            size="small"
            buttonStyle="solid"
            style={style}
            value={value}
            onChange={(e) => onChange && onChange(e.target.value)}
        >
            <Radio.Button value={StringMatching.Exact}>Exact match</Radio.Button>
            <Radio.Button value={StringMatching.Regex}>Regex</Radio.Button>
            <Radio.Button value={StringMatching.Contains}>Contains</Radio.Button>
        </Radio.Group>
    )
}
