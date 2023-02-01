import { Select } from 'antd'
import { PercentageOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { retentionLogic } from 'scenes/retention/retentionLogic'

export function RetentionReferencePicker(): JSX.Element {
    /*
        Reference picker specifies how retention values should be displayed,
        options and description found in `enum Reference`
    */
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionLogic(insightProps))
    const { setFilters } = useActions(retentionLogic(insightProps))

    return (
        <Select
            value={filters.retention_reference || 'total'}
            onChange={(retention_reference) => {
                setFilters({ retention_reference })
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
