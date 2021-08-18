import React, { useEffect, useState } from 'react'
import { Button, Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import equal from 'fast-deep-equal'
import clsx from 'clsx'
import { DeleteOutlined } from '@ant-design/icons'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS, clamp } from 'lib/utils'
import { FunnelExclusionEntityFilter, ActionFilter as ActionFilterType } from '~/types'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { getBreakpoint } from 'lib/utils/responsiveUtils'

import './FunnelExclusionsFilter.scss'

function ExclusionRowSuffix({
    filter,
    index,
    onClose,
}: {
    filter: ActionFilterType | FunnelExclusionEntityFilter
    index: number
    onClose: () => void
}): JSX.Element | null {
    const { exclusionFilters, exclusionDefaultStepRange, areFiltersValid, numberOfSeries } = useValues(funnelLogic)
    const { setOneEventExclusionFilter } = useActions(funnelLogic)

    const persistedStepRange = {
        funnel_from_step: exclusionFilters.events?.[index]?.funnel_from_step,
        funnel_to_step: exclusionFilters.events?.[index]?.funnel_to_step,
    }

    const [localStepRange, setLocalStepRange] = useState<Omit<FunnelExclusionEntityFilter, 'id' | 'name'>>(
        persistedStepRange ?? exclusionDefaultStepRange
    )

    const setExclusionRowValue = (): void => {
        setOneEventExclusionFilter({ ...filter, ...localStepRange }, index)
    }

    const onBlur = (): void => {
        if (!equal(persistedStepRange, localStepRange)) {
            setExclusionRowValue()
        }
    }

    const onChange = (fromStep: number, toStep: number): void => {
        const funnel_from_step = clamp(fromStep, 0, exclusionDefaultStepRange.funnel_to_step - 1)
        setLocalStepRange({
            funnel_from_step,
            funnel_to_step: clamp(toStep, funnel_from_step + 1, exclusionDefaultStepRange.funnel_to_step),
        })
    }

    useEffect(() => {
        onChange(localStepRange.funnel_from_step, localStepRange.funnel_to_step)
    }, [exclusionDefaultStepRange])

    return (
        <Row justify="space-between" align="middle" className="funnel-exclusion-row-wrapper">
            <Col className="funnel-exclusion-selectors">
                <div className="funnel-exclusion-funnel_from_step-selector">
                    between{' '}
                    <Select
                        defaultValue={0}
                        disabled={!areFiltersValid}
                        dropdownMatchSelectWidth={false}
                        dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                        data-attr="funnel-exclusion-funnel_from_step-selector"
                        optionLabelProp="label"
                        value={localStepRange.funnel_from_step}
                        onChange={(fromStep: number) => onChange(fromStep, localStepRange.funnel_to_step)}
                        onBlur={onBlur}
                    >
                        {Array.from(Array(numberOfSeries).keys())
                            .slice(0, -1)
                            .map((stepIndex) => (
                                <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                                    Step {stepIndex + 1}
                                </Select.Option>
                            ))}
                    </Select>
                </div>
                <div className="funnel-exclusion-funnel_to_step-selector">
                    and{' '}
                    <Select
                        defaultValue={(localStepRange.funnel_from_step ?? 0) + 1}
                        disabled={!areFiltersValid}
                        dropdownMatchSelectWidth={false}
                        dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                        data-attr="funnel-exclusion-funnel_to_step-selector"
                        optionLabelProp="label"
                        value={localStepRange.funnel_to_step}
                        onChange={(toStep: number) => onChange(localStepRange.funnel_from_step, toStep)}
                        onBlur={onBlur}
                    >
                        {Array.from(Array(numberOfSeries).keys())
                            .slice(localStepRange.funnel_from_step + 1)
                            .map((stepIndex) => (
                                <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                                    Step {stepIndex + 1}
                                </Select.Option>
                            ))}
                    </Select>
                </div>
            </Col>
            <Col>
                <Button
                    type="link"
                    onClick={onClose}
                    className="row-action-btn delete"
                    data-attr="delete-prop-exclusion-filter"
                    title="Delete event exclusion series"
                >
                    <DeleteOutlined />
                </Button>
            </Col>
        </Row>
    )
}

export function FunnelExclusionsFilter(): JSX.Element | null {
    const { exclusionFilters, areFiltersValid, exclusionDefaultStepRange } = useValues(funnelLogic)
    const { setEventExclusionFilters } = useActions(funnelLogic)
    const { width } = useWindowSize()
    const layoutBreakpoint = getBreakpoint('lg')
    const isVerticalLayout = !!width && width > layoutBreakpoint

    return (
        <ActionFilter
            setFilters={setEventExclusionFilters}
            filters={exclusionFilters}
            typeKey="funnel-exclusions-filter"
            addFilterDefaultOptions={exclusionDefaultStepRange}
            disabled={!areFiltersValid}
            buttonCopy="Add exclusion"
            groupTypes={[exclusionFilters.type as TaxonomicFilterGroupType]}
            hideMathSelector
            hidePropertySelector
            hideFilter
            hideDeleteBtn
            fullWidth
            rowClassName={clsx('funnel-exclusions-filter-row', { vertical: isVerticalLayout })}
            customRowSuffix={(filter, index, onClose) => (
                <ExclusionRowSuffix filter={filter} index={index} onClose={onClose} />
            )}
        />
    )
}
