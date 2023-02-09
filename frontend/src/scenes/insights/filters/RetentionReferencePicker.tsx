import { Select } from 'antd'
import { PercentageOutlined } from '@ant-design/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { retentionLogic } from 'scenes/retention/retentionLogic'
import { RetentionFilter } from '~/queries/schema'
import { insightDataLogic } from '../insightDataLogic'

export function RetentionReferencePickerDataExploration(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightDataLogic(insightProps))

    return <RetentionReferencePickerComponent {...retentionFilter} setFilters={updateInsightFilter} />
}

export function RetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionLogic(insightProps))
    const { setFilters } = useActions(retentionLogic(insightProps))

    return <RetentionReferencePickerComponent {...filters} setFilters={setFilters} />
}

type RetentionReferencePickerComponentProps = {
    setFilters: (filters: Partial<RetentionFilter>) => void
} & RetentionFilter

export function RetentionReferencePickerComponent({
    retention_reference,
    setFilters,
}: RetentionReferencePickerComponentProps): JSX.Element {
    return (
        <Select
            value={retention_reference || 'total'}
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
