import React from 'react'
import { Card, Loading } from '../../lib/utils'
import { Link } from 'react-router-dom'
import { actionsModel } from '../../models/actionsModel'
import { useValues, useActions } from 'kea'
import { funnelLogic } from './funnelLogic'
import { ActionFilter } from 'scenes/trends/ActionFilter/ActionFilter'
import { Button } from 'antd';

export function EditFunnel({ funnelId, onChange }) {
    const { funnel } = useValues(funnelLogic({ id: funnelId }))
    const { setFunnel, updateFunnel } = useActions(funnelLogic({ id: funnelId }))
    const { actions, actionsLoading } = useValues(actionsModel())
    return (
        <form
            onSubmit={e => {
                e.preventDefault()
                updateFunnel(funnel)
            }}
        >
            <Card>
                {funnel.filters ? (
                    <div className="card-body">
                        <input
                            required
                            placeholder="User drop off through signup"
                            type="text"
                            autoFocus
                            onChange={e => setFunnel({ name: e.target.value })}
                            value={funnel.name}
                            className="form-control"
                        />
                        {!actionsLoading && actions.length == 0 && (
                            <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                                You don't have any actions set up.{' '}
                                <Link to="/actions">Click here to set up an action</Link>
                            </div>
                        )}
                        <br />
                        <ActionFilter
                            setFilters={filters => setFunnel({ filters }, false)}
                            defaultFilters={funnel.filters}
                            typeKey="edit-funnel"
                        />
                        <br />
                        <Button type="primary" htmlType="submit">
                            Save funnel
                        </Button>
                    </div>
                ) : (
                    <Loading />
                )}
            </Card>
        </form>
    )
}
