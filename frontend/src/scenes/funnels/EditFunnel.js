import React from 'react'
import { Card, Loading } from '../../lib/utils'
import { Link } from 'react-router-dom'
import { actionsModel } from '../../models/actionsModel'
import { useValues, useActions } from 'kea'
import { funnelLogic } from './funnelLogic'
import { ActionFilter } from 'scenes/trends/ActionFilter/ActionFilter'
import { Button } from 'antd'

export function EditFunnel({ funnelId, onChange }) {
    const { funnel, isStepsEmpty } = useValues(funnelLogic({ id: funnelId }))
    const { setFunnel, updateFunnel, createFunnel } = useActions(funnelLogic({ id: funnelId }))
    const { actions, actionsLoading } = useValues(actionsModel())
    return (
        <form
            onSubmit={e => {
                e.preventDefault()
                if (!funnel.id) return createFunnel(funnel)
                updateFunnel(funnel)
            }}
        >
            <Card>
                <div className="card-body">
                    <input
                        required
                        placeholder="User drop off through signup"
                        type="text"
                        autoFocus
                        onChange={e => setFunnel({ name: e.target.value })}
                        value={funnel.name || ''}
                        className="form-control"
                    />
                    {!actionsLoading && actions.length == 0 && (
                        <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                            You don't have any actions set up. <Link to="/actions">Click here to set up an action</Link>
                        </div>
                    )}
                    <br />
                    <ActionFilter
                        setFilters={filters => setFunnel({ filters }, false)}
                        defaultFilters={funnel ? funnel.filters : {}}
                        typeKey="edit-funnel"
                    />
                    <br />
                    <Button type="primary" htmlType="submit" disabled={isStepsEmpty}>
                        Save funnel
                    </Button>
                    <br />
                    {isStepsEmpty && <small>Add some actions/events to save the funnel</small>}
                </div>
            </Card>
        </form>
    )
}
