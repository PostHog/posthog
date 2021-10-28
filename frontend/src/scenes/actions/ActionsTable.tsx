import React, { useState } from 'react'
import './Actions.scss'
import { Link } from 'lib/components/Link'
import { Input, Radio, Table } from 'antd'
import { QuestionCircleOutlined, DeleteOutlined, EditOutlined, ExportOutlined, CheckOutlined } from '@ant-design/icons'
import { DeleteWithUndo, stripHTTP, toParams } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { NewActionButton } from './NewActionButton'
import imgGrouping from 'public/actions-tutorial-grouping.svg'
import imgStandardized from 'public/actions-tutorial-standardized.svg'
import imgRetroactive from 'public/actions-tutorial-retroactive.svg'
import { ActionType, ViewType } from '~/types'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'
import { createdAtColumn, createdByColumn } from 'lib/components/Table/Table'
import { PageHeader } from 'lib/components/PageHeader'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import { ColumnType } from 'antd/lib/table'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { EventsTab, EventsTabs } from 'scenes/events'
import api from '../../lib/api'

const searchActions = (sources: ActionType[], search: string): ActionType[] => {
    return new Fuse(sources, {
        keys: ['name', 'url'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export const scene: SceneExport = {
    component: ActionsTable,
    logic: actionsModel,
    paramsToProps: () => ({ params: 'include_count=1' }),
}

export function ActionsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { actions, actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)
    const [searchTerm, setSearchTerm] = useState('')
    const [filterByMe, setFilterByMe] = useState(false)
    const { user } = useValues(userLogic)
    const tableScrollBreakpoint = getBreakpoint('lg')

    const columns: ColumnType<ActionType>[] = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a: ActionType, b: ActionType) => ('' + a.name).localeCompare(b.name),
            render: function RenderName(_: any, action: ActionType, index: number): JSX.Element {
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
                      render: function RenderVolume(action: ActionType): JSX.Element {
                          return <span>{action.count}</span>
                      },
                      sorter: (a: ActionType, b: ActionType) => (a.count || 0) - (b.count || 0),
                  },
              ]
            : []),
        {
            title: 'Type',
            render: function RenderType(action: ActionType): JSX.Element {
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
        ...(currentTeam?.slack_incoming_webhook
            ? [
                  {
                      title: 'Webhook',
                      key: 'post_to_slack',
                      sorter: (a: ActionType, b: ActionType) => Number(a.post_to_slack) - Number(b.post_to_slack),
                      render: function RenderActions(action: ActionType): JSX.Element | null {
                          return action.post_to_slack ? <CheckOutlined /> : null
                      },
                  },
              ]
            : []),
        {
            title: '',
            render: function RenderActions(action: ActionType): JSX.Element {
                const params = {
                    insight: ViewType.TRENDS,
                    interval: 'day',
                    display: 'ActionsLineGraph',
                    actions: [
                        {
                            id: action.id,
                            name: action.name,
                            type: 'actions',
                            order: 0,
                        },
                    ],
                }
                const encodedParams = toParams(params)

                const actionsLink = `/insights?${encodedParams}#backTo=Actions&backToURL=${window.location.pathname}`

                return (
                    <span>
                        <Link to={'/action/' + action.id + '#backTo=Actions&backToURL=' + window.location.pathname}>
                            <EditOutlined />
                        </Link>
                        <DeleteWithUndo
                            endpoint={api.actions.determineDeleteEndpoint()}
                            object={action}
                            className="text-danger"
                            style={{ marginLeft: 8, marginRight: 8 }}
                            callback={loadActions}
                        >
                            <DeleteOutlined />
                        </DeleteWithUndo>
                        <Link to={`${actionsLink}`} data-attr="actions-table-usage">
                            Insights <ExportOutlined />
                        </Link>
                    </span>
                )
            },
        },
    ]
    let data = actions
    if (searchTerm && searchTerm !== '') {
        data = searchActions(data, searchTerm)
    }
    if (filterByMe) {
        data = data.filter((item) => item.created_by?.uuid === user?.uuid)
    }

    return (
        <div data-attr="manage-events-table" style={{ paddingTop: 32 }}>
            <EventsTabs tab={EventsTab.Actions} />
            <PageHeader
                title="Actions"
                caption={
                    <>
                        Actions can retroactively group one or more raw events to help provide consistent analytics.{' '}
                        <a
                            href="https://posthog.com/docs/features/actions?utm_medium=in-product&utm_campaign=actions-table"
                            target="_blank"
                        >
                            <QuestionCircleOutlined />
                        </a>
                    </>
                }
                style={{ marginTop: 0 }}
            />
            <div>
                <div />
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
                                We'll retroactively update your actions to match any past events.
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
                scroll={{ x: `${tableScrollBreakpoint}px` }}
            />
        </div>
    )
}
