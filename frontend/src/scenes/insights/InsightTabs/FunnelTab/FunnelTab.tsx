import React, { useEffect } from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Row } from 'antd'
import { useState } from 'react'
import { SaveModal } from '../../SaveModal'
import { funnelCommandLogic } from './funnelCommandLogic'
import { InsightTitle } from '../InsightTitle'
import { InfoCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { ToggleButtonChartFilter } from './ToggleButtonChartFilter'
import { InsightActionBar } from '../InsightActionBar'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelStepOrderPicker } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepOrderPicker'

export function FunnelTab(): JSX.Element {
    useMountedLogic(funnelCommandLogic)
    const { isStepsEmpty, filters, stepsWithCount, clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const { loadResults, clearFunnel, setFilters, saveFunnelInsight } = useActions(funnelLogic)
    const [savingModal, setSavingModal] = useState<boolean>(false)

    const showModal = (): void => setSavingModal(true)
    const closeModal = (): void => setSavingModal(false)
    const onSubmit = (input: string): void => {
        saveFunnelInsight(input)
        closeModal()
    }

    return (
        <div data-attr="funnel-tab" className="funnel-tab">
            <InsightTitle
                actionBar={
                    clickhouseFeaturesEnabled ? (
                        <InsightActionBar
                            variant="sidebar"
                            filters={filters}
                            insight="FUNNELS"
                            showReset={!isStepsEmpty || !!filters.properties?.length}
                            onReset={(): void => clearFunnel()}
                        />
                    ) : undefined
                }
            />
            <ToggleButtonChartFilter />
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    loadResults()
                }}
            >
                <Row justify="space-between" align="middle">
                    <h4 className="secondary" style={{ marginBottom: 0 }}>
                        Steps
                    </h4>
                    {clickhouseFeaturesEnabled && (
                        <Row align="middle">
                            <span className="l5 text-muted-alt">
                                <span style={{ marginRight: 5 }}>Step Order</span>
                                <FunnelStepOrderPicker />
                                <Tooltip
                                    title={
                                        <ul style={{ paddingLeft: '1.2rem' }}>
                                            <li>
                                                <b>Sequential</b> - Step B must happen after Step A, but any number
                                                events can happen between A and B.
                                            </li>
                                            <li>
                                                <b>Strict Order</b> - Step B must happen directly after Step A without
                                                any events in between.
                                            </li>
                                            <li>
                                                <b>Any Order</b> - Steps can be completed in any sequence.
                                            </li>
                                        </ul>
                                    }
                                >
                                    <InfoCircleOutlined className="info-indicator" />
                                </Tooltip>
                            </span>
                        </Row>
                    )}
                </Row>
                <ActionFilter
                    filters={filters}
                    setFilters={(newFilters: Record<string, any>): void => setFilters(newFilters, false)}
                    typeKey={`EditFunnel-action`}
                    hideMathSelector={true}
                    buttonCopy="Add funnel step"
                    showSeriesIndicator={!isStepsEmpty}
                    seriesIndicatorType="numeric"
                    fullWidth
                    sortable
                    showNestedArrow={true}
                />

                {!clickhouseFeaturesEnabled && (
                    <>
                        <hr />
                        <Row style={{ justifyContent: 'flex-end' }}>
                            {!isStepsEmpty && Array.isArray(stepsWithCount) && !!stepsWithCount.length && (
                                <div style={{ flexGrow: 1 }}>
                                    <Button type="default" onClick={showModal} icon={<SaveOutlined />}>
                                        Save
                                    </Button>
                                </div>
                            )}
                            {!isStepsEmpty && (
                                <Button
                                    type="link"
                                    onClick={(): void => clearFunnel()}
                                    data-attr="save-funnel-clear-button"
                                >
                                    Clear
                                </Button>
                            )}
                            <CalculateFunnelButton style={{ marginLeft: 4 }} />
                        </Row>
                    </>
                )}
            </form>
            <SaveModal
                title="Save Funnel"
                prompt="Enter the name of the funnel"
                textLabel="Name"
                visible={savingModal}
                onCancel={closeModal}
                onSubmit={onSubmit}
            />
        </div>
    )
}

function CalculateFunnelButton({ style }: { style: React.CSSProperties }): JSX.Element {
    const { filters, areFiltersValid, filtersDirty, clickhouseFeaturesEnabled, isLoading } = useValues(funnelLogic)
    const [tooltipOpen, setTooltipOpen] = useState(false)
    const shouldRecalculate = filtersDirty && areFiltersValid && !isLoading && !clickhouseFeaturesEnabled

    // Only show tooltip after 3s of inactivity
    useEffect(() => {
        if (shouldRecalculate) {
            const rerenderInterval = setTimeout(() => {
                setTooltipOpen(true)
            }, 3000)

            return () => {
                clearTimeout(rerenderInterval)
                setTooltipOpen(false)
            }
        } else {
            setTooltipOpen(false)
        }
    }, [shouldRecalculate, filters])

    return (
        <Tooltip
            visible={tooltipOpen}
            title="Your query has changed. Calculate your changes to see updates in the visualization."
        >
            <Button
                style={style}
                type={shouldRecalculate ? 'primary' : 'default'}
                htmlType="submit"
                disabled={!areFiltersValid}
                data-attr="save-funnel-button"
            >
                Calculate
            </Button>
        </Tooltip>
    )
}
