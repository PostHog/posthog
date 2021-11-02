import React, { useRef } from 'react'
import { Button, Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import useSize from '@react-hook/size'
import { DeleteOutlined } from '@ant-design/icons'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS } from 'lib/utils'
import { FunnelStepRangeEntityFilter, ActionFilter as ActionFilterType, EntityTypes } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

function ExclusionRowSuffix({
    filter,
    index,
    onClose,
    isVertical,
}: {
    filter: ActionFilterType | FunnelStepRangeEntityFilter
    index: number
    onClose?: () => void
    isVertical: boolean
}): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters, areFiltersValid, numberOfSeries, exclusionDefaultStepRange } = useValues(funnelLogic(insightProps))
    const { setOneEventExclusionFilter } = useActions(funnelLogic(insightProps))

    const stepRange = {
        funnel_from_step: filters.exclusions?.[index]?.funnel_from_step ?? exclusionDefaultStepRange.funnel_from_step,
        funnel_to_step: filters.exclusions?.[index]?.funnel_to_step ?? exclusionDefaultStepRange.funnel_to_step,
    }

    const onChange = (
        funnel_from_step: number = stepRange.funnel_from_step,
        funnel_to_step: number = stepRange.funnel_to_step
    ): void => {
        setOneEventExclusionFilter(
            {
                ...filter,
                funnel_from_step,
                funnel_to_step,
            },
            index
        )
    }

    return (
        <Row
            justify="space-between"
            align="middle"
            wrap={false}
            style={{ margin: `${isVertical ? 4 : 0}px 0`, paddingLeft: 4, width: isVertical ? '100%' : 'auto' }}
        >
            between
            <Select
                defaultValue={0}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_from_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_from_step}
                onChange={(fromStep: number) => onChange(fromStep)}
                onBlur={() => onChange}
                style={{ marginLeft: 4, marginRight: 4 }}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice(0, -1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
            and
            <Select
                defaultValue={(stepRange.funnel_from_step ?? 0) + 1}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_to_step-selector"
                optionLabelProp="label"
                value={stepRange.funnel_to_step}
                onChange={(toStep: number) => onChange(stepRange.funnel_from_step, toStep)}
                onBlur={() => onChange}
                style={{ marginLeft: 4 }}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice((stepRange.funnel_from_step ?? 0) + 1)
                    .map((stepIndex) => (
                        <Select.Option key={stepIndex} value={stepIndex} label={`Step ${stepIndex + 1}`}>
                            Step {stepIndex + 1}
                        </Select.Option>
                    ))}
            </Select>
            <div style={{ flex: 1 }} />
            <Button
                type="link"
                onClick={onClose}
                className="row-action-btn delete"
                data-attr="delete-prop-exclusion-filter"
                title="Delete event exclusion series"
                style={{ marginLeft: 4 }}
            >
                <DeleteOutlined />
            </Button>
        </Row>
    )
}

function ExclusionRow({
    seriesIndicator,
    filter,
    suffix,
    isVertical,
}: {
    seriesIndicator?: JSX.Element | string
    suffix?: JSX.Element | string
    filter?: JSX.Element | string
    isVertical?: boolean
}): JSX.Element {
    return (
        <Row wrap={false} align={isVertical ? 'top' : 'middle'} style={{ width: '100%' }}>
            <Col style={{ padding: `${isVertical ? 5 : 0}px 8px` }}>{seriesIndicator}</Col>
            <Col flex="auto">
                <Row align="middle" wrap={isVertical}>
                    {filter}
                    {suffix}
                </Row>
            </Col>
        </Row>
    )
}

export function FunnelExclusionsFilter(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { exclusionFilters, areFiltersValid, exclusionDefaultStepRange } = useValues(funnelLogic(insightProps))
    const { setEventExclusionFilters } = useActions(funnelLogic(insightProps))
    const ref = useRef(null)
    const [width] = useSize(ref)
    const isVerticalLayout = !!width && width < 450 // If filter container shrinks below 500px, initiate verticality

    return (
        <ActionFilter
            ref={ref}
            setFilters={setEventExclusionFilters}
            filters={exclusionFilters}
            typeKey="funnel-exclusions-filter"
            addFilterDefaultOptions={{
                id: '$pageview',
                name: '$pageview',
                type: EntityTypes.EVENTS,
                ...exclusionDefaultStepRange,
            }}
            disabled={!areFiltersValid}
            buttonCopy="Add exclusion"
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
            hideMathSelector
            hidePropertySelector
            hideFilter
            hideRename
            hideDeleteBtn
            fullWidth
            seriesIndicatorType="alpha"
            renderRow={(props) => <ExclusionRow {...props} isVertical={isVerticalLayout} />}
            customRowSuffix={(props) => <ExclusionRowSuffix {...props} isVertical={isVerticalLayout} />}
        />
    )
}
