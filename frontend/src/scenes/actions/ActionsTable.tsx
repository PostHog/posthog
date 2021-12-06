import React, { useState } from 'react'
import './Actions.scss'
import { Link } from 'lib/components/Link'
import { Input, Radio } from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import { deleteWithUndo, stripHTTP } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { NewActionButton } from './NewActionButton'
import imgGrouping from 'public/actions-tutorial-grouping.svg'
import imgStandardized from 'public/actions-tutorial-standardized.svg'
import imgRetroactive from 'public/actions-tutorial-retroactive.svg'
import { ActionType, ChartDisplayType, InsightType } from '~/types'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { EventsTab } from 'scenes/events'
import api from 'lib/api'
import { urls } from '../urls'
import { EventPageHeader } from 'scenes/events/EventPageHeader'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable/types'
import { LemonTable } from 'lib/components/LemonTable'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonSpacer } from 'lib/components/LemonRow'
import { More } from 'lib/components/LemonButton/More'
import { combineUrl } from 'kea-router'

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
}

export function ActionsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { actions, actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)
    const [searchTerm, setSearchTerm] = useState('')
    const [filterByMe, setFilterByMe] = useState(false)
    const { user } = useValues(userLogic)

    const columns: LemonTableColumns<ActionType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            width: '30%',
            sorter: (a: ActionType, b: ActionType) => ('' + a.name).localeCompare(b.name),
            render: function RenderName(name, action: ActionType, index: number): JSX.Element {
                return (
                    <Link data-attr={'action-link-' + index} to={urls.action(action.id)}>
                        <h4 className="row-name">{name || <i>Unnnamed action</i>}</h4>
                    </Link>
                )
            },
        },
        {
            title: 'Type',
            key: 'type',
            render: function RenderType(_, action: ActionType): JSX.Element {
                return (
                    <span>
                        {action.steps?.length ? (
                            action.steps.map((step) => (
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
                            ))
                        ) : (
                            <i>Empty – set this action up</i>
                        )}
                    </span>
                )
            },
        },
        createdByColumn() as LemonTableColumn<ActionType, keyof ActionType | undefined>,
        createdAtColumn() as LemonTableColumn<ActionType, keyof ActionType | undefined>,
        ...(currentTeam?.slack_incoming_webhook
            ? [
                  {
                      title: 'Webhook',
                      dataIndex: 'post_to_slack',
                      sorter: (a: ActionType, b: ActionType) => Number(a.post_to_slack) - Number(b.post_to_slack),
                      render: function RenderActions(post_to_slack): JSX.Element | null {
                          return post_to_slack ? <CheckOutlined /> : null
                      },
                  } as LemonTableColumn<ActionType, keyof ActionType | undefined>,
              ]
            : []),
        {
            width: 0,
            render: function RenderActions(_, action) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton type="stealth" to={urls.action(action.id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    to={
                                        combineUrl(
                                            urls.insightNew({
                                                insight: InsightType.TRENDS,
                                                interval: 'day',
                                                display: ChartDisplayType.ActionsLineGraphLinear,
                                                actions: [
                                                    {
                                                        id: action.id,
                                                        name: action.name,
                                                        type: 'actions',
                                                        order: 0,
                                                    },
                                                ],
                                            })
                                        ).url
                                    }
                                    fullWidth
                                >
                                    Try out in Insights
                                </LemonButton>
                                <LemonSpacer />
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() =>
                                        deleteWithUndo({
                                            endpoint: api.actions.determineDeleteEndpoint(),
                                            object: action,
                                            callback: loadActions,
                                        })
                                    }
                                    fullWidth
                                >
                                    Delete action
                                </LemonButton>
                            </>
                        }
                    />
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
        <div data-attr="manage-events-table">
            <EventPageHeader activeTab={EventsTab.Actions} />
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
                placeholder="Search for actions"
                allowClear
                enterButton
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
            <LemonTable
                columns={columns}
                loading={actionsLoading}
                rowKey="id"
                pagination={{ pageSize: 30 }}
                data-attr="actions-table"
                dataSource={data}
                defaultSorting={{
                    columnKey: 'created_by',
                    order: -1,
                }}
                emptyState="The first step to standardized analytics is creating your first action."
            />
        </div>
    )
}
