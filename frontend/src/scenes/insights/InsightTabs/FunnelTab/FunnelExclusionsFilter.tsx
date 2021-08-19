import React, { useEffect, useRef, useState } from 'react'
import { Button, Col, Row, Select } from 'antd'
import { useActions, useValues } from 'kea'
import equal from 'fast-deep-equal'
import useSize from '@react-hook/size'
import { DeleteOutlined } from '@ant-design/icons'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ANTD_TOOLTIP_PLACEMENTS, areObjectValuesEmpty, clamp } from 'lib/utils'
import { FunnelExclusionEntityFilter, ActionFilter as ActionFilterType, EntityTypes } from '~/types'

function ExclusionRowSuffix({
    filter,
    index,
    onClose,
    isVertical,
}: {
    filter: ActionFilterType | FunnelExclusionEntityFilter
    index: number
    onClose?: () => void
    isVertical: boolean
}): JSX.Element | null {
    const { exclusionFilters, exclusionDefaultStepRange, areFiltersValid, numberOfSeries } = useValues(funnelLogic)
    const { setOneEventExclusionFilter } = useActions(funnelLogic)

    const persistedStepRange = {
        funnel_from_step: exclusionFilters.events?.[index]?.funnel_from_step,
        funnel_to_step: exclusionFilters.events?.[index]?.funnel_to_step,
    }

    const [localStepRange, setLocalStepRange] = useState<Omit<FunnelExclusionEntityFilter, 'id' | 'name'>>(
        !areObjectValuesEmpty(persistedStepRange) ? persistedStepRange : exclusionDefaultStepRange
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
        <Row
            justify="space-between"
            align="middle"
            wrap={false}
            style={{ margin: `${isVertical ? 4 : 0}px 0`, paddingLeft: 4, width: '100%' }}
        >
            between
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
                defaultValue={(localStepRange.funnel_from_step ?? 0) + 1}
                disabled={!areFiltersValid}
                dropdownMatchSelectWidth={false}
                dropdownAlign={ANTD_TOOLTIP_PLACEMENTS.bottomRight}
                data-attr="funnel-exclusion-funnel_to_step-selector"
                optionLabelProp="label"
                value={localStepRange.funnel_to_step}
                onChange={(toStep: number) => onChange(localStepRange.funnel_from_step, toStep)}
                onBlur={onBlur}
                style={{ marginLeft: 4 }}
            >
                {Array.from(Array(numberOfSeries).keys())
                    .slice((localStepRange.funnel_from_step ?? 0) + 1)
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
    const { exclusionFilters, areFiltersValid, exclusionDefaultStepRange } = useValues(funnelLogic)
    const { setEventExclusionFilters } = useActions(funnelLogic)
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
            groupTypes={[exclusionFilters.type as TaxonomicFilterGroupType]}
            hideMathSelector
            hidePropertySelector
            hideFilter
            hideDeleteBtn
            fullWidth
            seriesIndicatorType="alpha"
            renderRow={(props) => <ExclusionRow {...props} isVertical={isVerticalLayout} />}
            customRowSuffix={(props) => <ExclusionRowSuffix {...props} isVertical={isVerticalLayout} />}
        />
    )
}
