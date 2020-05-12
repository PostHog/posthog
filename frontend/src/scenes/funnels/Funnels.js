import React from 'react'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { DeleteWithUndo } from 'lib/utils'
import { funnelsModel } from '../../models/funnelsModel'
import { useActions, useValues } from 'kea'
import { Table } from 'antd'

export function Funnels() {
    const { funnels, funnelsLoading } = useValues(funnelsModel)
    const { loadFunnels } = useActions(funnelsModel)
    let columns = [
        {
            title: 'Funnel Name',
            dataIndex: 'name',
            key: 'name',
            render: (_, funnel) => <Link to={`/funnel/${funnel.id}`}>{funnel.name}</Link>,
        },
        {
            title: 'Actions',
            render: funnel => (
                <span>
                    <DeleteWithUndo endpoint="funnel" object={funnel} className="text-danger" callback={loadFunnels}>
                        <i className="fi flaticon-basket" />
                    </DeleteWithUndo>
                </span>
            ),
        },
    ]
    return (
        <div>
            <h1>Funnels</h1>
            <p style={{ maxWidth: 600 }}>
                <i>
                    If you need your users to carry out a series of actions in a row, funnels are a way of working out
                    where users are dropping off.{' '}
                    <a href="https://github.com/PostHog/posthog/wiki/Funnels" target="_blank">
                        See documentation
                    </a>
                </i>
            </p>
            <LinkButton to={'/funnel/new'} type="primary">
                + New Funnel
            </LinkButton>
            <br />
            <br />
            <Table
                size="small"
                columns={columns}
                loading={!funnels && funnelsLoading}
                rowKey={funnel => funnel.id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                dataSource={funnels}
            />
        </div>
    )
}
