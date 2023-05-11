import { useState } from 'react'
import { Link } from 'lib/lemon-ui/Link'
import { Radio } from 'antd'
import { deleteWithUndo, stripHTTP } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { NewActionButton } from './NewActionButton'
import { ActionStepType, ActionType, AvailableFeature, ChartDisplayType, InsightType } from '~/types'
import Fuse from 'fuse.js'
import { userLogic } from 'scenes/userLogic'
import { teamLogic } from '../teamLogic'
import { SceneExport } from 'scenes/sceneTypes'
import api from 'lib/api'
import { urls } from '../urls'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable/types'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { combineUrl } from 'kea-router'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonInput, LemonModal, lemonToast } from '@posthog/lemon-ui'
import { actionsLogic } from 'scenes/actions/actionsLogic'
import { IconCheckmark, IconPlayCircle } from 'lib/lemon-ui/icons'

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
    logic: actionsLogic,
}

export function ActionsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { actions, actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)
    const [searchTerm, setSearchTerm] = useState('')
    const [filterByMe, setFilterByMe] = useState(false)
    const [dupVisible, setDupVisible] = useState(false)
    const [dupName, setDupName] = useState('')
    const [dupAction, setDupAction] = useState<ActionType>()
    const { user, hasAvailableFeature } = useValues(userLogic)

    const duplicateAction = async (action: ActionType | undefined): Promise<void> => {
        if (action) {
            try {
                const { id, action_id, ...partialAction } = action
                const newActionSteps: ActionStepType[] | undefined = action.steps?.map(({ id, ...partialStep }) => ({
                    ...partialStep,
                }))
                await api.actions.create({
                    ...partialAction,
                    name: dupName,
                    steps: newActionSteps,
                })
                loadActions()
                lemonToast.success('Action duplicated')
            } catch (response: any) {
                if (response.type === 'validation_error' && response.code === 'unique') {
                } else {
                    lemonToast.error(
                        <>
                            Couldn't create this action. You can try{' '}
                            <Link to={urls.createAction()}>manually creating an action instead.</Link>
                        </>
                    )
                    return
                }
            }
        }
    }
    const columns: LemonTableColumns<ActionType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            width: '25%',
            sorter: (a: ActionType, b: ActionType) => (a.name || '').localeCompare(b.name || ''),
            render: function RenderName(name, action: ActionType, index: number): JSX.Element {
                return (
                    <Link data-attr={'action-link-' + index} to={urls.action(action.id)} className="row-name">
                        {name || <i>Unnamed action</i>}
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
        ...(hasAvailableFeature(AvailableFeature.TAGGING)
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags',
                      width: 250,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  } as LemonTableColumn<ActionType, keyof ActionType | undefined>,
              ]
            : []),
        createdByColumn() as LemonTableColumn<ActionType, keyof ActionType | undefined>,
        createdAtColumn() as LemonTableColumn<ActionType, keyof ActionType | undefined>,
        ...(currentTeam?.slack_incoming_webhook
            ? [
                  {
                      title: 'Webhook',
                      dataIndex: 'post_to_slack',
                      sorter: (a: ActionType, b: ActionType) => Number(a.post_to_slack) - Number(b.post_to_slack),
                      render: function RenderActions(post_to_slack): JSX.Element | null {
                          return post_to_slack ? <IconCheckmark /> : null
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
                                <LemonButton status="stealth" to={urls.action(action.id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    to={
                                        combineUrl(urls.sessionRecordings(), {
                                            filters: {
                                                actions: [
                                                    {
                                                        id: action.id,
                                                        type: 'actions',
                                                        order: 0,
                                                        name: action.name,
                                                    },
                                                ],
                                            },
                                        }).url
                                    }
                                    sideIcon={<IconPlayCircle />}
                                    fullWidth
                                    data-attr="action-table-view-recordings"
                                >
                                    View recordings
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    to={
                                        combineUrl(
                                            urls.insightNew({
                                                insight: InsightType.TRENDS,
                                                interval: 'day',
                                                display: ChartDisplayType.ActionsLineGraph,
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
                                <LemonButton
                                    status="stealth"
                                    onClick={() => {
                                        setDupName(action.name?.toString() ?? '')
                                        setDupVisible(true)
                                        setDupAction(action)
                                    }}
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
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
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
                buttons={<NewActionButton />}
            />
            <DataManagementPageTabs tab={DataManagementTab.Actions} />
            <div className="flex items-center justify-between gap-2 mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for actions"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <Radio.Group buttonStyle="solid" value={filterByMe} onChange={(e) => setFilterByMe(e.target.value)}>
                    <Radio.Button value={false}>All actions</Radio.Button>
                    <Radio.Button value={true}>My actions</Radio.Button>
                </Radio.Group>
            </div>
            <LemonTable
                columns={columns}
                loading={actionsLoading}
                rowKey="id"
                pagination={{ pageSize: 100 }}
                data-attr="actions-table"
                dataSource={data}
                defaultSorting={{
                    columnKey: 'created_by',
                    order: -1,
                }}
                emptyState="The first step to standardized analytics is creating your first action."
            />
            <LemonModal
                isOpen={dupVisible}
                onClose={() => {
                    setDupVisible(false)
                }}
                title={`Duplicate action`}
                footer={
                    <>
                        <LemonButton
                            key="duplicate-button"
                            type="primary"
                            onClick={() => {
                                setDupVisible(false)
                                duplicateAction(dupAction)
                            }}
                        >
                            Duplicate
                        </LemonButton>
                        <LemonButton
                            key="cancel-button"
                            type="secondary"
                            onClick={() => {
                                setDupVisible(false)
                            }}
                        >
                            Cancel
                        </LemonButton>
                    </>
                }
            >
                <LemonInput
                    type="text"
                    placeholder="Enter name for duplicated action"
                    onChange={setDupName}
                    value={dupName}
                />
            </LemonModal>
        </div>
    )
}
