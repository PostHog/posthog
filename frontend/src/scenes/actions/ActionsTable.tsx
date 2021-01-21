import React, { useState } from 'react'
import './Actions.scss'
import { Link } from 'lib/components/Link'
import { Input, Radio, Table } from 'antd'
import { QuestionCircleOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { DeleteWithUndo, stripHTTP } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { NewActionButton } from './NewActionButton'
import imgGrouping from 'public/actions-tutorial-grouping.svg'
import imgStandardized from 'public/actions-tutorial-standardized.svg'
import imgRetroactive from 'public/actions-tutorial-retroactive.svg'
import { ActionType } from '~/types'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'

const searchActions = (sources: ActionType[], search: string): ActionType[] => {
    return new Fuse(sources, {
        keys: ['name', 'url'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export function ActionsTable(): JSX.Element {
    const { actions, actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)
    const [searchTerm, setSearchTerm] = useState(false)
    const [filterByMe, setFilterByMe] = useState(false)
    const { user } = useValues(userLogic)

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            sorter: (a: ActionType, b: ActionType) => ('' + a.name).localeCompare(b.name),
            render: function RenderName(_, action: ActionType, index: number) {
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
                      render: function RenderVolume(_, action: ActionType) {
                          return <span>{action.count}</span>
                      },
                      sorter: (a: ActionType, b: ActionType) => (a.count || 0) - (b.count || 0),
                  },
              ]
            : []),
        {
            title: 'Type',
            render: function RenderType(_, action: ActionType) {
                return (
                    <span>
                        {action.steps?.map((step) => (
                            <div key={step.id}>
                                {(() => {
                                    let url = stripHTTP(step.url || '')
                                    url = url.slice(0, 40) + (url.length > 40 ? '...' : '')
                                    switch (step.event) {
                                        case '$autocapture':
                                            return 'Autocapture'
                                        case '$pageview':
                                            switch (step.url_matching) {
                                                case 'regex':
                                                    return (
                                                        <>
                                                            Page view URL matches regex <strong>{url}</strong>
                                                        </>
                                                    )
                                                case 'exact':
                                                    return (
                                                        <>
                                                            Page view URL matches exactly <strong>{url}</strong>
                                                        </>
                                                    )
                                                default:
                                                    return (
                                                        <>
                                                            Page view URL contains <strong>{url}</strong>
                                                        </>
                                                    )
                                            }
                                        default:
                                            return (
                                                <>
                                                    Event: <strong>{step.event}</strong>
                                                </>
                                            )
                                    }
                                })()}
                            </div>
                        ))}
                    </span>
                )
            },
        },
        createdAtColumn(),
        createdByColumn(actions),
        {
            title: '',
            render: function RenderActions(action: ActionType) {
                return (
                    <span>
                        <Link to={'/action/' + action.id + '#backTo=Actions&backToURL=' + window.location.pathname}>
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
    let data = actions
    if (searchTerm) {
        data = searchActions(data, searchTerm)
    }
    if (filterByMe) {
        data = data.filter((item) => item.created_by?.id === user?.id)
    }

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

            <Input.Search
                allowClear
                enterButton
                autoFocus
                style={{ maxWidth: 600, width: 'initial', flexGrow: 1, marginRight: 12 }}
                onChange={(e) => {
                    setSearchTerm(e.target.value)
                }}
            />
            <Radio.Group buttonStyle="solid" value={filterByMe} onChange={(e) => setFilterByMe(e.target.value)}>
                <Radio.Button value={false}>All actions</Radio.Button>
                <Radio.Button value={true}>My actions</Radio.Button>
            </Radio.Group>

            <div className="mb float-right">
                <NewActionButton />
            </div>
            <br />
            <Table
                size="small"
                columns={columns}
                loading={actionsLoading}
                rowKey="id"
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                data-attr="actions-table"
                dataSource={data}
                locale={{ emptyText: 'The first step to standardized analytics is creating your first action.' }}
            />
        </div>
    )
}
