import React from 'react'
import { useValues, useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { actionsModel } from '~/models/actionsModel'
import { userLogic } from 'scenes/userLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { Link } from 'lib/components/Link'
import { Button, Row } from 'antd'

export function FunnelTab(): JSX.Element {
    const { isStepsEmpty, filters } = useValues(funnelLogic)
    const { loadFunnel, clearFunnel, setFilters } = useActions(funnelLogic)
    const { actions, actionsLoading } = useValues(actionsModel)
    const { eventProperties } = useValues(userLogic)

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
                <Row justify="start">
                    <Button type="primary" htmlType="submit" disabled={isStepsEmpty} data-attr="save-funnel-button">
                        Calculate
                    </Button>
                    {!isStepsEmpty && (
                        <Button onClick={(): void => clearFunnel()} data-attr="save-funnel-clear-button">
                            Clear
                        </Button>
                    )}
                </Row>
            </form>
        </div>
    )
}
