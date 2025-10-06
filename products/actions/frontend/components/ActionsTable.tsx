import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { stripHTTP } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { actionsModel } from '~/models/actionsModel'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { ActionType, AvailableFeature, ChartDisplayType, FilterLogicalOperator, ProductKey, ReplayTabs } from '~/types'

import { actionsLogic } from '../logics/actionsLogic'
import { NewActionButton } from './NewActionButton'

export function ActionsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions, pinAction, unpinAction } = useActions(actionsModel)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { filterType, searchTerm, actionsFiltered, shouldShowEmptyState } = useValues(actionsLogic)
    const { setFilterType, setSearchTerm } = useActions(actionsLogic)

    const { hasAvailableFeature } = useValues(userLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    const tryInInsightsUrl = (action: ActionType): string => {
        const query: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        id: action.id,
                        name: action.name || undefined,
                        kind: NodeKind.ActionsNode,
                    },
                ],
                interval: 'day',
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            },
        }
        return urls.insightNew({ query })
    }

    const columns: LemonTableColumns<ActionType> = [
        {
            width: 0,
            title: 'Pinned',
            dataIndex: 'pinned_at',
            sorter: (a: ActionType, b: ActionType) =>
                (b.pinned_at ? new Date(b.pinned_at).getTime() : 0) -
                (a.pinned_at ? new Date(a.pinned_at).getTime() : 0),
            render: function Render(pinned, action) {
                return (
                    <LemonButton
                        size="small"
                        onClick={pinned ? () => unpinAction(action) : () => pinAction(action)}
                        tooltip={pinned ? 'Unpin action' : 'Pin action'}
                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                    />
                )
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            width: '25%',
            sorter: (a: ActionType, b: ActionType) => (a.name || '').localeCompare(b.name || ''),
            render: function RenderName(_, action: ActionType, index: number): JSX.Element {
                return (
                    <LemonTableLink
                        data-attr={'action-link-' + index}
                        to={urls.action(action.id)}
                        title={action.name || <i>Unnamed</i>}
                        description={action.description}
                    />
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
                            action.steps.map((step, index) => (
                                <div key={index}>
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
                                            case '':
                                            case null:
                                            case undefined:
                                                return 'Any event'
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
                          return post_to_slack ? <IconCheckCircle /> : null
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
                                <LemonButton to={urls.action(action.id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton to={urls.duplicateAction(action)} fullWidth>
                                    Duplicate
                                </LemonButton>
                                <LemonButton
                                    to={urls.replay(ReplayTabs.Home, {
                                        filter_group: {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    type: FilterLogicalOperator.And,
                                                    values: [
                                                        {
                                                            id: action.id,
                                                            type: 'actions',
                                                            order: 0,
                                                            name: action.name,
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    })}
                                    onClick={() => {
                                        addProductIntentForCrossSell({
                                            from: ProductKey.ACTIONS,
                                            to: ProductKey.SESSION_REPLAY,
                                            intent_context: ProductIntentContext.ACTION_VIEW_RECORDINGS,
                                        })
                                    }}
                                    sideIcon={<IconPlayCircle />}
                                    fullWidth
                                    data-attr="action-table-view-recordings"
                                    targetBlank
                                >
                                    View recordings
                                </LemonButton>
                                <LemonButton to={tryInInsightsUrl(action)} fullWidth targetBlank>
                                    Try out in Insights
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => {
                                        deleteWithUndo({
                                            endpoint: api.actions.determineDeleteEndpoint(),
                                            object: action,
                                            callback: loadActions,
                                        }).catch((e: any) => {
                                            lemonToast.error(`Error deleting action: ${e.detail}`)
                                        })
                                    }}
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

    return (
        <div data-attr="manage-events-table">
            <ProductIntroduction
                productName="Actions"
                productKey={ProductKey.ACTIONS}
                thingName="action"
                isEmpty={shouldShowEmptyState}
                description="Use actions to combine events that you want to have tracked together or to make detailed Autocapture events easier to reuse."
                docsURL="https://posthog.com/docs/data/actions"
                actionElementOverride={
                    <NewActionButton onSelectOption={() => updateHasSeenProductIntroFor(ProductKey.ACTIONS)} />
                }
            />
            {(shouldShowEmptyState && filterType === 'me') || !shouldShowEmptyState ? (
                <div className="flex items-center justify-between gap-2 mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for actions"
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                    <LemonSegmentedButton
                        value={filterType}
                        onChange={setFilterType}
                        options={[
                            { value: 'all', label: 'All actions' },
                            { value: 'me', label: 'My actions' },
                        ]}
                    />
                </div>
            ) : null}
            {(!shouldShowEmptyState || filterType === 'me') && (
                <>
                    <LemonTable
                        columns={columns}
                        loading={actionsLoading}
                        rowKey="id"
                        pagination={{ pageSize: 100 }}
                        data-attr="actions-table"
                        dataSource={actionsFiltered}
                        defaultSorting={{
                            columnKey: 'created_by',
                            order: -1,
                        }}
                        emptyState="No results. Create a new action?"
                    />
                </>
            )}
        </div>
    )
}
