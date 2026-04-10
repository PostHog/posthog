import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { StickinessOperator } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyOperator } from '~/types'

export function StickinessCriteria({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const stickinessCriteria = stickinessFilter?.stickinessCriteria
    const currentOperator = stickinessCriteria?.operator ?? PropertyOperator.GreaterThanOrEqual
    const currentValue = stickinessCriteria?.value ?? 1

    const operators: StickinessOperator[] = [
        PropertyOperator.LessThanOrEqual,
        PropertyOperator.GreaterThanOrEqual,
        PropertyOperator.Exact,
    ]

    return (
        <div className="flex items-center gap-2 @min-[0px]/editor-panel:flex-wrap">
            <div className="flex-1 @min-[0px]/editor-panel:flex-none @min-[0px]/editor-panel:min-w-0">
                <OperatorSelect
                    operator={currentOperator}
                    operators={operators}
                    onChange={(newOperator: PropertyOperator) => {
                        updateInsightFilter({
                            stickinessCriteria: { operator: newOperator as StickinessOperator, value: currentValue },
                        })
                    }}
                />
            </div>
            <LemonInput
                type="number"
                className="w-20"
                defaultValue={currentValue}
                min={1}
                onChange={(newValue: number | undefined) => {
                    if (newValue !== undefined) {
                        updateInsightFilter({ stickinessCriteria: { operator: currentOperator, value: newValue } })
                    }
                }}
            />
            <span className="@min-[0px]/editor-panel:whitespace-nowrap">time(s) per interval</span>
        </div>
    )
}
