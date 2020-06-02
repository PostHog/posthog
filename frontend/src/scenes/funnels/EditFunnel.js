import React from 'react'
import { Card } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { actionsModel } from '~/models/actionsModel'
import { useValues, useActions } from 'kea'
import { funnelLogic } from './funnelLogic'
import { ActionFilter } from 'scenes/trends/ActionFilter/ActionFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Button } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { hot } from 'react-hot-loader/root'

export const EditFunnel = hot(_EditFunnel)
function _EditFunnel({ funnelId }) {
    const { funnel, isStepsEmpty } = useValues(funnelLogic({ id: funnelId }))
    const { setFunnel, updateFunnel, createFunnel } = useActions(funnelLogic({ id: funnelId }))
    const { actions, actionsLoading } = useValues(actionsModel())
    const { eventProperties } = useValues(userLogic)

    return (
        <form
            onSubmit={e => {
                e.preventDefault()
                if (!funnel.id) {
                    createFunnel(funnel)
                } else {
                    updateFunnel(funnel)
                }
            }}
        >
            <Card>
                <div className="card-body" data-attr="funnel-editor">
                    <input
                        required
                        placeholder="Name of Funnel: (e.g. User drop off through signup)"
                        type="text"
                        autoFocus
                        onChange={e => setFunnel({ name: e.target.value })}
                        value={funnel.name || ''}
                        className="form-control"
                        data-attr="edit-funnel-input"
                    />
                    {!actionsLoading && actions.length === 0 && (
                        <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                            You don't have any actions set up. <Link to="/actions">Click here to set up an action</Link>
                        </div>
                    )}
                    <br />
                    <ActionFilter
                        filters={funnel.filters}
                        setFilters={filters => setFunnel({ filters }, false)}
                        typeKey={`EditFunnel-${funnel.id || 'new'}`}
                    />
                    <br />
                    <hr />
                    <h4 className="secondary mt-3">Filters</h4>
                    <PropertyFilters
                        pageKey={`EditFunnel-${funnel.id || 'new'}`}
                        properties={eventProperties}
                        propertyFilters={funnel.filters.properties || []}
                        onChange={properties =>
                            setFunnel({
                                filters: {
                                    properties,
                                },
                            })
                        }
                        style={{ marginBottom: 20 }}
                    />
                    <hr />
                    <Button
                        type="primary mt-3"
                        htmlType="submit"
                        disabled={isStepsEmpty}
                        data-attr="save-funnel-button"
                    >
                        Save funnel
                    </Button>
                    <br />
                </div>
            </Card>
        </form>
    )
}
