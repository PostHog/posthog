import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Row } from 'antd'
import { useState } from 'react'
import { SaveModal } from '../../SaveModal'
import { funnelCommandLogic } from './funnelCommandLogic'
import { InsightTitle } from '../InsightTitle'
import { SaveOutlined } from '@ant-design/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { ToggleButtonChartFilter } from './ToggleButtonChartFilter'
import { InsightActionBar } from '../InsightActionBar'

export function FunnelTab(): JSX.Element {
    useMountedLogic(funnelCommandLogic)
    const { isStepsEmpty, areFiltersValid, filters, stepsWithCount, clickhouseFeaturesEnabled } = useValues(funnelLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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
            {featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && <ToggleButtonChartFilter />}
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    loadResults()
                }}
            >
                <h4 className="secondary">Steps</h4>
                <ActionFilter
                    filters={filters}
                    setFilters={(newFilters: Record<string, any>): void => setFilters(newFilters, false)}
                    typeKey={`EditFunnel-action`}
                    hideMathSelector={true}
                    buttonCopy="Add funnel step"
                    showSeriesIndicator={!isStepsEmpty && featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]}
                    seriesIndicatorType="numeric"
                    fullWidth={featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]}
                    sortable
                    showNestedArrow={true}
                />

                {!clickhouseFeaturesEnabled && (
                    <>
                        <hr />
                        <Row style={{ justifyContent: 'flex-end' }}>
                            {!isStepsEmpty && Array.isArray(stepsWithCount) && !!stepsWithCount.length && (
                                <div style={{ flexGrow: 1 }}>
                                    <Button type="primary" onClick={showModal} icon={<SaveOutlined />}>
                                        Save
                                    </Button>
                                </div>
                            )}
                            {!isStepsEmpty && (
                                <Button onClick={(): void => clearFunnel()} data-attr="save-funnel-clear-button">
                                    Clear
                                </Button>
                            )}

                            <Button
                                style={{ marginLeft: 4 }}
                                type="primary"
                                htmlType="submit"
                                disabled={!areFiltersValid}
                                data-attr="save-funnel-button"
                            >
                                Calculate
                            </Button>
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
