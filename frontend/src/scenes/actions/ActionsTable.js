import React from 'react'
import './Actions.scss'
import { Link } from 'lib/components/Link'
import { Table, Tooltip } from 'antd'
import { QuestionCircleOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { DeleteWithUndo } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { NewActionButton } from './NewActionButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import moment from 'moment'
import imgGrouping from 'public/actions-tutorial-grouping.svg'
import imgStandardized from 'public/actions-tutorial-standardized.svg'
import imgRetroactive from 'public/actions-tutorial-retroactive.svg'

export function ActionsTable() {
    const { actions, actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    let columns = [
        {
            title: !featureFlags['actions-ux-201012'] ? 'Action ID' : 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function RenderName(_, action, index) {
                return (
                    <Link
                        data-attr={'action-link-' + index}
                        to={'/action/' + action.id + '#backTo=Actions&backToURL=' + window.location.pathname}
                    >
                        {action.name}
                    </Link>
                )
            },
        },
        ...(actions[0]?.count !== null
            ? [
                  {
                      title: 'Volume',
                      render: function RenderVolume(_, action) {
                          return <span>{action.count}</span>
                      },
                  },
              ]
            : []),
        {
            title: 'Type',
            render: function RenderType(_, action) {
                return (
                    <span>
                        {action.steps.map((step) => (
                            <div key={step.id}>
                                {(() => {
                                    switch (step.event) {
                                        case '$autocapture':
                                            return 'Autocapture'
                                        case '$pageview':
                                            switch (step.url_matching) {
                                                case 'regex':
                                                    return 'Page view URL matches regex'
                                                case 'exact':
                                                    return 'Page view URL matches exactly'
                                                default:
                                                    return 'Page view URL contains'
                                            }
                                        default:
                                            return 'Event: ' + step.event
                                    }
                                })()}
                            </div>
                        ))}
                    </span>
                )
            },
        },
        {
            title: 'Created by',
            render: function RenderCreatedBy(_, action) {
                if (!action.created_by) return 'Unknown'
                return action.created_by.first_name || action.created_by.email
            },
        },
        {
            title: 'Created',
            render: function RenderCreatedAt(_, action) {
                return (
                    <Tooltip title={moment(action.created_at).format('LLL')}>
                        {moment(action.created_at).fromNow()}
                    </Tooltip>
                )
            },
        },
        {
            title: !featureFlags['actions-ux-201012'] ? 'Actions' : '',
            render: function RenderActions(action) {
                return (
                    <span>
                        <Link to={'/action/' + action.id}>
                            <EditOutlined />
                        </Link>
                        <DeleteWithUndo
                            endpoint="action"
                            object={action}
                            className="text-danger"
                            style={{ marginLeft: 8 }}
                            callback={loadActions}
                        >
                            <DeleteOutlined />
                        </DeleteWithUndo>
                    </span>
                )
            },
        },
    ]

    return (
        <div>
            <div>
                <div>
                    Actions can retroactively group one or more raw events to help provide consistent analytics.{' '}
                    <a href="https://posthog.com/docs/features/actions" target="_blank">
                        <QuestionCircleOutlined />
                    </a>
                </div>
                <div className="tutorial-container">
                    <div className="t-element">
                        <div>
                            <img src={imgGrouping} alt="" />
                        </div>
                        <div>
                            <div className="title">Multiple grouping</div>
                            <div className="description">Group multiple sets of events into a single action.</div>
                        </div>
                    </div>
                    <div className="t-element">
                        <div>
                            <img src={imgStandardized} alt="" />
                        </div>
                        <div>
                            <div className="title">Clean &amp; standardized data</div>
                            <div className="description">
                                Keep your actions the same, even if your product or data changes.
                            </div>
                        </div>
                    </div>
                    <div className="t-element">
                        <div>
                            <img src={imgRetroactive} alt="" />
                        </div>
                        <div>
                            <div className="title">Retroactive</div>
                            <div className="description">
                                We'll retroactive update your actions to match any past events.
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div className="mb text-right">
                <NewActionButton />
            </div>
            <Table
                size="small"
                columns={columns}
                loading={actionsLoading}
                rowKey={(action) => action.id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                data-attr="actions-table"
                dataSource={actions}
                locale={{ emptyText: 'The first step to standardized analytics is creating your first action.' }}
            />
        </div>
    )
}
