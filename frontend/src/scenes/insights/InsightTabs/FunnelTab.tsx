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
    const { funnel, isStepsEmpty } = useValues(funnelLogic({ id: null }))
    const { setFunnel, updateFunnel, createFunnel, clearFunnel } = useActions(funnelLogic({ id: null }))
    const { actions, actionsLoading } = useValues(actionsModel())
    const { eventProperties } = useValues(userLogic)

    return (
        <div data-attr="funnel-tab">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    if (!funnel.id) {
                        createFunnel(funnel)
                    } else {
                        updateFunnel(funnel)
                    }
                }}
            >
                <h4 className="secondary">Funnel Name</h4>
                <input
                    required
                    placeholder="Name of Funnel: (e.g. User drop off through signup)"
                    type="text"
                    autoFocus
                    onChange={(e): void => setFunnel({ name: e.target.value })}
                    value={funnel.name || ''}
                    className="form-control"
                    data-attr="edit-funnel-input"
                />
                {!actionsLoading && actions.length === 0 && (
                    <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                        You don't have any actions set up. <Link to="/actions">Click here to set up an action</Link>
                    </div>
                )}
                <hr />
                <h4 className="secondary">Steps</h4>
                <ActionFilter
                    filters={funnel.filters}
                    setFilters={(filters): void => setFunnel({ filters }, false)}
                    typeKey={`EditFunnel-${funnel.id || 'new'}`}
                    hideMathSelector={true}
                />
                <hr />
                <h4 className="secondary">Filters</h4>
                <PropertyFilters
                    pageKey={`EditFunnel-${funnel.id || 'new'}`}
                    properties={eventProperties}
                    propertyFilters={funnel.filters.properties || []}
                    onChange={(properties): void =>
                        setFunnel({
                            filters: {
                                properties,
                            },
                        })
                    }
                    style={{ marginBottom: 20 }}
                />
                <hr />
                <Row justify="start">
                    <Button type="primary" htmlType="submit" disabled={isStepsEmpty} data-attr="save-funnel-button">
                        Save funnel
                    </Button>
                    {funnel.id && (
                        <Button
                            onClick={(): void => clearFunnel()}
                            className="ml-2"
                            data-attr="save-funnel-clear-button"
                        >
                            Clear
                        </Button>
                    )}
                </Row>
            </form>
        </div>
    )
}
