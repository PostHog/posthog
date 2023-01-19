import { useActions, useValues } from 'kea'
import { Select } from 'antd'
import { BarsOutlined } from '@ant-design/icons'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'

import { pathsLogic, DEFAULT_STEP_LIMIT } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, EditorFilterProps, PathsFilterType, QueryEditorFilterProps } from '~/types'

interface StepOption {
    label: string
    value: number
}

export function PathStepPickerDataExploration({
    insightProps,
}: Pick<QueryEditorFilterProps, 'insightProps'>): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return <PathStepPickerComponent setFilter={updateInsightFilter} {...insightFilter} />
    return <></>
}

export function PathStepPicker({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return <PathStepPickerComponent setFilter={setFilter} {...filter} />
}

type PathStepPickerComponentProps = {
    setFilter: (filter: PathsFilterType) => void
} & PathsFilterType

export function PathStepPickerComponent({ step_limit, setFilter }: PathStepPickerComponentProps): JSX.Element {
    const { user } = useValues(userLogic)

    const MIN = 2,
        MAX = user?.organization?.available_features.includes(AvailableFeature.PATHS_ADVANCED) ? 20 : 5

    const options: StepOption[] = Array.from(Array.from(Array.from(Array(MAX + 1).keys()).slice(MIN)), (v) => ({
        label: `${v} Steps`,
        value: v,
    }))

    return (
        <Select
            id="path-step-filter"
            data-attr="path-step-filter"
            defaultValue={5}
            value={step_limit || DEFAULT_STEP_LIMIT}
            onSelect={(count) => setFilter({ step_limit: count })}
            listHeight={440}
            bordered={false}
            dropdownMatchSelectWidth={true}
            dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
            optionLabelProp="label"
        >
            {options.map((option) => {
                return (
                    <Select.Option
                        key={option.value}
                        value={option.value}
                        label={
                            <>
                                <BarsOutlined /> {option.label}
                            </>
                        }
                    >
                        {option.label}
                    </Select.Option>
                )
            })}
        </Select>
    )
}
