import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconCheckmark, IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable/types'
import { Link } from 'lib/lemon-ui/Link'
import { stripHTTP } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { actionsLogic } from 'scenes/actions/actionsLogic'
import { userLogic } from 'scenes/userLogic'

import { actionsModel } from '~/models/actionsModel'
import { ActionType, AvailableFeature, ChartDisplayType, InsightType, ProductKey } from '~/types'

import { NewActionButton } from '../../actions/NewActionButton'
import { teamLogic } from '../../teamLogic'
import { urls } from '../../urls'

export function ActionsTable(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { actionsLoading } = useValues(actionsModel({ params: 'include_count=1' }))
    const { loadActions } = useActions(actionsModel)

    const { filterType, searchTerm, actionsFiltered, shouldShowProductIntroduction, shouldShowEmptyState } =
        useValues(actionsLogic)
    const { setFilterType, setSearchTerm } = useActions(actionsLogic)

    const { hasAvailableFeature } = useValues(userLogic)
    const { updateHasSeenProductIntroFor } = useActions(userLogic)

    const columns: LemonTableColumns<ActionType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            width: '25%',
            sorter: (a: ActionType, b: ActionType) => (a.name || '').localeCompare(b.name || ''),
            render: function RenderName(name, action: ActionType, index: number): JSX.Element {
                return (
                    <>
                        <Link data-attr={'action-link-' + index} to={urls.action(action.id)} className="row-name">
                            {name || <i>Unnamed action</i>}
                        </Link>
                        {action.description && (
                            <LemonMarkdown className="row-description" lowKeyHeadings>
                                {action.description}
                            </LemonMarkdown>
                        )}
                    </>
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
                                <LemonButton status="stealth" to={urls.copyAction(action)} fullWidth>
                                    Copy
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    to={
                                        combineUrl(urls.replay(), {
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
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() =>
                                        void deleteWithUndo({
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

    return (
        <div data-attr="manage-events-table">
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                <ProductIntroduction
                    productName="Actions"
                    productKey={ProductKey.ACTIONS}
                    thingName="action"
                    isEmpty={shouldShowEmptyState}
                    description="Use actions to combine events that you want to have tracked together or to make detailed Autocapture events easier to reuse."
                    docsURL="https://posthog.com/docs/data/actions"
                    actionElementOverride={
                        <NewActionButton
                            onSelectOption={() => updateHasSeenProductIntroFor(ProductKey.ACTIONS, true)}
                        />
                    }
                />
            )}
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
