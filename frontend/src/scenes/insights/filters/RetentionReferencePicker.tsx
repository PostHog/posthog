// eslint-disable-next-line no-restricted-imports
import { PercentageOutlined } from '@ant-design/icons'
import { Select } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const { retention_reference } = retentionFilter || {}
    return (
        <Select
            value={retention_reference || 'total'}
            onChange={(retention_reference) => {
                updateInsightFilter({ retention_reference })
            }}
            bordered={false}
            dropdownMatchSelectWidth={false}
            data-attr="reference-selector"
            optionLabelProp="label"
        >
            {[
                {
                    value: 'total',
                    icon: <PercentageOutlined />,
                    label: 'Overall cohort',
                },
                {
                    value: 'previous',
                    icon: <PercentageOutlined />,
                    label: 'Relative to previous period',
                },
            ].map((option) => (
                <Select.Option
                    key={option.value}
                    value={option.value}
                    label={
                        <>
                            {option.icon} {option.label}
                        </>
                    }
                >
                    {option.label}
                </Select.Option>
            ))}
        </Select>
    )
}
