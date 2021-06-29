import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Button, Row } from 'antd'
import { useState } from 'react'
import { SaveModal } from '../../SaveModal'
import { funnelCommandLogic } from './funnelCommandLogic'
import { TestAccountFilter } from 'scenes/insights/TestAccountFilter'
import { InsightTitle } from '../InsightTitle'
import { SaveOutlined } from '@ant-design/icons'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

export function FunnelTab(): JSX.Element {
    useMountedLogic(funnelCommandLogic)
    const { isStepsEmpty, filters, stepsWithCount } = useValues(funnelLogic())
    const { loadResults, clearFunnel, setFilters, saveFunnelInsight } = useActions(funnelLogic())
    const [savingModal, setSavingModal] = useState<boolean>(false)

    const showModal = (): void => setSavingModal(true)
    const closeModal = (): void => setSavingModal(false)
    const onSubmit = (input: string): void => {
        saveFunnelInsight(input)
        closeModal()
    }

    return (
        <div data-attr="funnel-tab">
            <Row>
                <InsightTitle />
            </Row>
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
                    sortable
                />
                <hr />
                <h4 className="secondary">Filters</h4>
                <PropertyFilters
                    pageKey={`EditFunnel-property`}
                    propertyFilters={filters.properties || []}
                    onChange={(anyProperties) => {
                        setFilters({
                            properties: anyProperties.filter(isValidPropertyFilter),
                        })
                    }}
                />
                <TestAccountFilter filters={filters} onChange={setFilters} />
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
                        disabled={isStepsEmpty}
                        data-attr="save-funnel-button"
                    >
                        Calculate
                    </Button>
                </Row>
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
