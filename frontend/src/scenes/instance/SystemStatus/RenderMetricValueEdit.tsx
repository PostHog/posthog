import { LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

import { MetricValue } from './RenderMetricValue'

interface MetricValueEditInterface extends MetricValue {
    onValueChanged: (key: string, value: any) => void
}

export function RenderMetricValueEdit({
    key,
    value,
    value_type,
    onValueChanged,
}: MetricValueEditInterface): JSX.Element | string {
    if (value_type === 'bool') {
        return (
            <LemonCheckbox
                defaultChecked={!!value}
                onChange={(val) => onValueChanged(key, val)}
                label={
                    <LemonTag type={value ? 'success' : 'danger'} className="uppercase">
                        {value ? 'Yes' : 'No'}
                    </LemonTag>
                }
            />
        )
    }

    const parsedValue = Array.isArray(value) ? value.join(', ') : (value as string | number)

    return (
        <LemonInput
            defaultValue={parsedValue as any}
            type={value_type === 'int' ? 'number' : 'text'}
            placeholder={value_type === 'list[int]' ? 'e.g. 1, 2, 3' : undefined}
            onBlur={(e) => onValueChanged(key, e.target.value)}
        />
    )
}
