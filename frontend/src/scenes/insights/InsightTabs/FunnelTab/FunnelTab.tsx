import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'
import { ActionFilter } from '../../ActionFilter/ActionFilter'
import { Link } from 'lib/components/Link'
import { Button, Row } from 'antd'
import { useState } from 'react'
import SaveModal from '../../SaveModal'
import { funnelCommandLogic } from './funnelCommandLogic'

export function FunnelTab(): JSX.Element {
    useMountedLogic(funnelCommandLogic)
    const { isStepsEmpty, filters, stepsWithCount } = useValues(funnelLogic)
    const { loadFunnel, clearFunnel, setFilters, saveFunnelInsight } = useActions(funnelLogic)
    const { actions, actionsLoading } = useValues(actionsModel)
    const { eventProperties } = useValues(userLogic)
    const [savingModal, setSavingModal] = useState<boolean>(false)

    const showModal = (): void => setSavingModal(true)
    const closeModal = (): void => setSavingModal(false)
    const onSubmit = (input: string): void => {
        saveFunnelInsight(input)
        closeModal()
    }

    return (
        <div data-attr="funnel-tab">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    loadFunnel()
                }}
            >
                {!actionsLoading && actions.length === 0 && (
                    <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                        You don't have any actions set up. <Link to="/actions">Click here to set up an action</Link>
                    </div>
                )}
                <h4 className="secondary">Steps</h4>
                <ActionFilter
                    filters={filters}
                    setFilters={(filters): void => setFilters(filters, false)}
                    typeKey={`EditFunnel-action`}
                    hideMathSelector={true}
                    copy="Add funnel step"
                    sortable
                />
                <hr />
                <h4 className="secondary">Filters</h4>
                <PropertyFilters
                    pageKey={`EditFunnel-property`}
                    properties={eventProperties}
                    propertyFilters={filters.properties || []}
                    onChange={(properties): void =>
                        setFilters({
                            properties,
                        })
                    }
                    style={{ marginBottom: 20 }}
                />
                <hr />
                <Row justify="space-between">
                    <Row justify="start">
                        <Button
                            style={{ marginRight: 4 }}
                            type="primary"
                            htmlType="submit"
                            disabled={isStepsEmpty}
                            data-attr="save-funnel-button"
                        >
                            Calculate
                        </Button>
                        {!isStepsEmpty && (
                            <Button onClick={(): void => clearFunnel()} data-attr="save-funnel-clear-button">
                                Clear
                            </Button>
                        )}
                    </Row>
                    {!isStepsEmpty && Array.isArray(stepsWithCount) && !!stepsWithCount.length && (
                        <Button type="primary" onClick={showModal}>
                            Save
                        </Button>
                    )}
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
