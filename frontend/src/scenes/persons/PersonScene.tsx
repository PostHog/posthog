import { IconAIText, IconChevronDown, IconCopy, IconInfo, IconTarget } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonMenu, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { RelatedGroups } from 'scenes/groups/RelatedGroups'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    ActivityScope,
    NotebookNodeType,
    PersonsTabType,
    PersonType,
    ProductKey,
    PropertyDefinitionType,
} from '~/types'

import { MergeSplitPerson } from './MergeSplitPerson'
import { PersonCohorts } from './PersonCohorts'
import PersonFeedCanvas from './PersonFeedCanvas'
import { personsLogic } from './personsLogic'
import { RelatedFeatureFlags } from './RelatedFeatureFlags'
import { useState } from 'react'
import { Spinner } from 'lib/lemon-ui/Spinner'
import React from 'react'
import { IconPlayCircle } from 'lib/lemon-ui/icons'

export const scene: SceneExport = {
    component: PersonScene,
    logic: personsLogic,
    paramsToProps: ({ params: { _: rawUrlId } }): (typeof personsLogic)['props'] => ({
        syncWithUrl: true,
        urlId: decodeURIComponent(rawUrlId),
    }),
}

function PersonCaption({ person }: { person: PersonType }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <div className="flex deprecated-space-x-1">
                <div>
                    <span className="text-secondary">IDs:</span>{' '}
                    <CopyToClipboardInline
                        tooltipMessage={null}
                        description="person distinct ID"
                        style={{ justifyContent: 'flex-end' }}
                    >
                        {person.distinct_ids[0]}
                    </CopyToClipboardInline>
                </div>
                {person.distinct_ids.length > 1 && (
                    <LemonMenu
                        items={person.distinct_ids.slice(1).map((distinct_id: string) => ({
                            label: distinct_id,
                            sideIcon: <IconCopy className="text-primary-3000" />,
                            onClick: () => copyToClipboard(distinct_id, 'distinct id'),
                        }))}
                    >
                        <LemonTag type="primary" className="inline-flex">
                            <span>+{person.distinct_ids.length - 1}</span>
                            <IconChevronDown className="w-4 h-4" />
                        </LemonTag>
                    </LemonMenu>
                )}
            </div>
            <div>
                <span className="text-secondary">First seen:</span>{' '}
                {person.created_at ? <TZLabel time={person.created_at} /> : 'unknown'}
            </div>
            <div>
                <span className="text-secondary">Merge restrictions:</span> {person.is_identified ? 'applied' : 'none'}
                <Link to="https://posthog.com/docs/data/identify#alias-assigning-multiple-distinct-ids-to-the-same-user">
                    <Tooltip
                        title={
                            <>
                                {person.is_identified ? <strong>Cannot</strong> : 'Can'} be used as `alias_id` - click
                                for more info.
                            </>
                        }
                    >
                        <IconInfo className="ml-1 text-base shrink-0" />
                    </Tooltip>
                </Link>
            </div>
        </div>
    )
}

interface CriticalIssue {
    description: string
    sessions: {
        id: string
        timestamp: string
        hasRecording: boolean
        summary: string
    }[]
}

interface EdgeCase {
    description: string
    sessions: {
        id: string
        timestamp: string
        hasRecording: boolean
        summary: string
    }[]
}

interface SummaryDetails {
    criticalIssues: CriticalIssue[]
    commonJourneys: { name: string; path: string }[]
    edgeCases: EdgeCase[]
    summary: string
}

interface SummaryData {
    id: number
    period: string
    sessionsAnalyzed: number
    keyInsights: number
    pains: number
    status: 'success' | 'failure'
    details: SummaryDetails
}

function SessionSegmentCollapse({
    header,
    content,
    isFailed,
}: {
    header: React.ReactNode
    content: React.ReactNode
    isFailed?: boolean
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className="border rounded">
            <div className="cursor-pointer" onClick={() => setIsExpanded(!isExpanded)}>
                <div className="p-2">
                    <div className="flex items-center justify-between">
                        {header}
                        <IconChevronDown className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                    </div>
                </div>
            </div>
            {isExpanded && <div className="border-t p-2">{content}</div>}
        </div>
    )
}

function PersonSummariesTable(): JSX.Element {
    const sampleData: SummaryData[] = [
        {
            id: 1,
            period: '2024-03-01 to 2024-03-15',
            sessionsAnalyzed: 12,
            keyInsights: 5,
            pains: 2,
            status: 'success',
            details: {
                criticalIssues: [
                    {
                        description: 'Authentication timeouts during morning sessions',
                        sessions: [
                            {
                                id: '0196d2be-108d-7a79-8048-e5234ad7bdc9',
                                timestamp: '2024-03-15 09:15:23',
                                hasRecording: true,
                                summary:
                                    'User attempted to log in 3 times, each attempt timed out after 30 seconds. Network latency was high during these attempts.',
                            },
                            {
                                id: '0196d2bd-288d-73ea-970d-3d7f38e1707f',
                                timestamp: '2024-03-14 09:30:45',
                                hasRecording: true,
                                summary:
                                    'Similar timeout pattern observed. User switched networks after second attempt.',
                            },
                        ],
                    },
                    {
                        description: 'Paywall interruptions when accessing historical data',
                        sessions: [
                            {
                                id: '0196d2bd-515c-7230-9e15-a2a437f2e3e3',
                                timestamp: '2024-03-13 14:20:10',
                                hasRecording: false,
                                summary:
                                    'User hit paywall while trying to access data from Q4 2023. Attempted to refresh page multiple times.',
                            },
                        ],
                    },
                ],
                commonJourneys: [
                    {
                        name: 'Morning Analytics Review',
                        path: 'Login → Dashboard → Analytics → Filter by Date → Export Data',
                    },
                    {
                        name: 'Error Investigation',
                        path: 'Session Replay → Error Details → Team Assignment → Documentation',
                    },
                    {
                        name: 'Data Export Workflow',
                        path: 'Analytics → Filter by Date → Split Range → Export → Verify → Download',
                    },
                ],
                edgeCases: [
                    {
                        description: 'Consistently attempts to bulk export data despite size limitations',
                        sessions: [
                            {
                                id: '0196d2bd-515c-7230-9e15-a2a437f2e3e4',
                                timestamp: '2024-03-12 15:30:22',
                                hasRecording: true,
                                summary:
                                    'User attempted to export 12 months of data in one go, hitting the 100MB limit. Repeated the attempt 3 times with different date ranges.',
                            },
                            {
                                id: '0196d2bd-515c-7230-9e15-a2a437f2e3e5',
                                timestamp: '2024-03-11 14:15:33',
                                hasRecording: true,
                                summary:
                                    'Similar bulk export attempt with 6 months of data. System warned about size but user proceeded anyway.',
                            },
                        ],
                    },
                    {
                        description: 'Regular workaround: splits large date ranges into smaller chunks',
                        sessions: [
                            {
                                id: '0196d2bd-515c-7230-9e15-a2a437f2e3e6',
                                timestamp: '2024-03-10 11:45:12',
                                hasRecording: true,
                                summary:
                                    'User manually split a 3-month export into 3 separate 1-month exports. Took 15 minutes to complete all exports.',
                            },
                        ],
                    },
                    {
                        description: 'Often uses browser back button when encountering paywalls',
                        sessions: [
                            {
                                id: '0196d2bd-515c-7230-9e15-a2a437f2e3e7',
                                timestamp: '2024-03-09 16:20:45',
                                hasRecording: true,
                                summary:
                                    'User hit paywall, used back button 3 times to try different navigation paths. Eventually found a way to access the data through a different route.',
                            },
                        ],
                    },
                ],
                summary:
                    'User shows consistent morning activity patterns with focus on data analysis. Regularly encounters authentication and data size limitations, but has developed workarounds. Most productive during early sessions before encountering performance issues.',
            },
        },
        {
            id: 2,
            period: '2024-02-15 to 2024-02-29',
            sessionsAnalyzed: 8,
            keyInsights: 3,
            pains: 1,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 3,
            period: '2024-02-01 to 2024-02-14',
            sessionsAnalyzed: 15,
            keyInsights: 7,
            pains: 3,
            status: 'failure',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 4,
            period: '2024-01-15 to 2024-01-31',
            sessionsAnalyzed: 10,
            keyInsights: 4,
            pains: 2,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 5,
            period: '2024-01-01 to 2024-01-14',
            sessionsAnalyzed: 6,
            keyInsights: 2,
            pains: 1,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 6,
            period: '2023-12-15 to 2023-12-31',
            sessionsAnalyzed: 9,
            keyInsights: 4,
            pains: 2,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 7,
            period: '2023-12-01 to 2023-12-14',
            sessionsAnalyzed: 11,
            keyInsights: 5,
            pains: 2,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 8,
            period: '2023-11-15 to 2023-11-30',
            sessionsAnalyzed: 7,
            keyInsights: 3,
            pains: 1,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 9,
            period: '2023-11-01 to 2023-11-14',
            sessionsAnalyzed: 13,
            keyInsights: 6,
            pains: 3,
            status: 'failure',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 10,
            period: '2023-10-15 to 2023-10-31',
            sessionsAnalyzed: 8,
            keyInsights: 3,
            pains: 1,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 11,
            period: '2023-10-01 to 2023-10-14',
            sessionsAnalyzed: 5,
            keyInsights: 2,
            pains: 1,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
        {
            id: 12,
            period: '2023-09-15 to 2023-09-30',
            sessionsAnalyzed: 9,
            keyInsights: 4,
            pains: 2,
            status: 'success',
            details: {
                criticalIssues: [],
                commonJourneys: [],
                edgeCases: [],
                summary: 'No detailed analysis available for this period.',
            },
        },
    ]

    return (
        <LemonTable
            dataSource={sampleData}
            columns={[
                {
                    title: 'Summary Period',
                    dataIndex: 'period',
                    width: 200,
                },
                {
                    title: 'Sessions Analyzed',
                    dataIndex: 'sessionsAnalyzed',
                    width: 150,
                },
                {
                    title: 'Key Insights',
                    dataIndex: 'keyInsights',
                    width: 120,
                },
                {
                    title: 'Pains',
                    dataIndex: 'pains',
                    width: 100,
                },
                {
                    title: 'Status',
                    dataIndex: 'status',
                    width: 120,
                    render: ((dataValue: string | number | SummaryDetails | undefined, record: SummaryData) => {
                        const status = record.status
                        return (
                            <LemonTag type={status === 'success' ? 'success' : 'danger'}>
                                {status.charAt(0).toUpperCase() + status.slice(1)}
                            </LemonTag>
                        )
                    }) as (dataValue: string | number | SummaryDetails | undefined, record: SummaryData) => JSX.Element,
                },
            ]}
            expandable={{
                expandedRowRender: (record: SummaryData) => (
                    <div className="px-4 py-2 bg-bg-light">
                        <div className="flex flex-col">
                            <h3 className="text-lg font-semibold mb-4 mt-2 flex items-center gap-2">
                                <IconAIText />
                                Person's Session Analysis
                                <LemonTag type="completion" size="medium">
                                    ALPHA
                                </LemonTag>
                            </h3>

                            <div className="mb-2">
                                <LemonBanner type={record.status === 'success' ? 'success' : 'error'} className="mb-4">
                                    <div className="text-sm font-normal">
                                        <div>{record.details.summary}</div>
                                    </div>
                                </LemonBanner>
                                <LemonDivider />
                            </div>

                            <div className="space-y-8">
                                <div>
                                    <div className="flex items-center gap-2 mb-4">
                                        <h4 className="text-lg font-semibold m-0">Critical Issues</h4>
                                        <LemonTag type="danger" size="small">
                                            {record.details.criticalIssues.length} issues
                                        </LemonTag>
                                    </div>
                                    <div className="space-y-2">
                                        {record.details.criticalIssues.map((issue: CriticalIssue, i: number) => (
                                            <SessionSegmentCollapse
                                                key={i}
                                                isFailed={true}
                                                header={
                                                    <div className="flex flex-row gap-2 items-center">
                                                        <h3 className="text-sm font-medium mb-0">
                                                            {issue.description}
                                                        </h3>
                                                        <LemonTag size="small" type="default">
                                                            {issue.sessions.length} sessions
                                                        </LemonTag>
                                                    </div>
                                                }
                                                content={
                                                    <div className="space-y-0">
                                                        {issue.sessions.map((session, j) => (
                                                            <div key={j}>
                                                                <div className="text-sm py-2">
                                                                    <div className="flex items-center justify-between mb-1">
                                                                        <div className="flex items-center gap-2">
                                                                            <span className="text-muted">
                                                                                {session.timestamp}
                                                                            </span>
                                                                            <span className="text-muted">•</span>
                                                                            <span className="text-muted">
                                                                                {session.id}
                                                                            </span>
                                                                        </div>
                                                                        <div className="flex gap-1">
                                                                            <LemonButton
                                                                                sideIcon={<IconTarget />}
                                                                                size="xsmall"
                                                                                type="secondary"
                                                                            >
                                                                                <span>View moment</span>
                                                                            </LemonButton>
                                                                            <LemonButton
                                                                                sideIcon={<IconPlayCircle />}
                                                                                size="xsmall"
                                                                                type="secondary"
                                                                            >
                                                                                View recording
                                                                            </LemonButton>
                                                                        </div>
                                                                    </div>
                                                                    <p className="mb-0">{session.summary}</p>
                                                                </div>
                                                                {j < issue.sessions.length - 1 && (
                                                                    <div className="h-px bg-border" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                }
                                            />
                                        ))}
                                    </div>
                                </div>

                                <div>
                                    <div className="flex items-center gap-2 mb-4">
                                        <h4 className="text-lg font-semibold m-0">Common User Journeys</h4>
                                        <LemonTag type="default" size="small">
                                            {record.details.commonJourneys.length} patterns
                                        </LemonTag>
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        {record.details.commonJourneys.map(
                                            (journey: { name: string; path: string }, i: number) => (
                                                <div key={i} className="bg-bg-light border rounded p-3">
                                                    <div className="flex items-center gap-2 mb-2">
                                                        <h3 className="text-sm font-medium mb-0">{journey.name}</h3>
                                                        <LemonTag size="small" type="default">
                                                            common
                                                        </LemonTag>
                                                    </div>
                                                    <div className="flex items-center gap-1 text-sm">
                                                        {journey.path.split(' → ').map((step, j) => (
                                                            <React.Fragment key={j}>
                                                                {j > 0 && (
                                                                    <IconChevronDown className="w-4 h-4 rotate-270 text-muted" />
                                                                )}
                                                                <span className="text-muted">{step}</span>
                                                            </React.Fragment>
                                                        ))}
                                                    </div>
                                                </div>
                                            )
                                        )}
                                    </div>
                                </div>

                                <div className="mb-4">
                                    <div className="flex items-center gap-2 mb-4">
                                        <h4 className="text-lg font-semibold m-0">Interesting Edge Cases</h4>
                                        <LemonTag type="default" size="small">
                                            {record.details.edgeCases.length} cases
                                        </LemonTag>
                                    </div>
                                    <div className="space-y-2">
                                        {record.details.edgeCases.map((edgeCase: EdgeCase, i: number) => (
                                            <SessionSegmentCollapse
                                                key={i}
                                                header={
                                                    <div className="flex flex-row gap-2 items-center">
                                                        <h3 className="text-sm font-medium mb-0">
                                                            {edgeCase.description}
                                                        </h3>
                                                        <LemonTag size="small" type="default">
                                                            {edgeCase.sessions.length} sessions
                                                        </LemonTag>
                                                    </div>
                                                }
                                                content={
                                                    <div className="space-y-0">
                                                        {edgeCase.sessions.map((session, j) => (
                                                            <div key={j}>
                                                                <div className="text-sm py-2">
                                                                    <div className="flex items-center justify-between mb-1">
                                                                        <div className="flex items-center gap-2">
                                                                            <span className="text-muted">
                                                                                {session.timestamp}
                                                                            </span>
                                                                            <span className="text-muted">•</span>
                                                                            <span className="text-muted">
                                                                                {session.id}
                                                                            </span>
                                                                        </div>
                                                                        <div className="flex gap-1">
                                                                            <LemonButton
                                                                                sideIcon={<IconTarget />}
                                                                                size="xsmall"
                                                                                type="secondary"
                                                                            >
                                                                                <span>View moment</span>
                                                                            </LemonButton>
                                                                            <LemonButton
                                                                                sideIcon={<IconPlayCircle />}
                                                                                size="xsmall"
                                                                                type="secondary"
                                                                            >
                                                                                View recording
                                                                            </LemonButton>
                                                                        </div>
                                                                    </div>
                                                                    <p className="mb-0">{session.summary}</p>
                                                                </div>
                                                                {j < edgeCase.sessions.length - 1 && (
                                                                    <div className="h-px bg-border" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                }
                                            />
                                        ))}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                ),
                rowExpandable: () => true,
                noIndent: true,
            }}
        />
    )
}

export function PersonScene(): JSX.Element | null {
    const {
        feedEnabled,
        person,
        personLoading,
        personError,
        currentTab,
        splitMergeModalShown,
        urlId,
        distinctId,
        primaryDistinctId,
    } = useValues(personsLogic)
    const { loadPersons, editProperty, deleteProperty, navigateToTab, setSplitMergeModalShown, setDistinctId } =
        useActions(personsLogic)
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { deletedPersonLoading } = useValues(personDeleteModalLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    if (personError) {
        throw new Error(personError)
    }
    if (!person) {
        return personLoading ? <SpinnerOverlay sceneLevel /> : <NotFound object="Person" meta={{ urlId }} />
    }

    const url = urls.personByDistinctId(urlId || person.distinct_ids[0] || String(person.id))
    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <>
            <PageHeader
                caption={<PersonCaption person={person} />}
                notebookProps={
                    url
                        ? {
                              href: url,
                          }
                        : undefined
                }
                buttons={
                    <div className="flex gap-2">
                        <NotebookSelectButton
                            resource={{
                                type: NotebookNodeType.Person,
                                attrs: { id: person?.distinct_ids[0] },
                            }}
                            type="secondary"
                        />
                        <LemonButton
                            icon={<IconAIText />}
                            disabled={deletedPersonLoading}
                            loading={deletedPersonLoading}
                            type="secondary"
                            data-attr="delete-person"
                        >
                            Summarize sessions
                        </LemonButton>
                        <LemonButton
                            onClick={() => showPersonDeleteModal(person, () => loadPersons())}
                            disabled={deletedPersonLoading}
                            loading={deletedPersonLoading}
                            type="secondary"
                            status="danger"
                            data-attr="delete-person"
                        >
                            Delete person
                        </LemonButton>

                        {person.distinct_ids.length > 1 && (
                            <LemonButton
                                onClick={() => setSplitMergeModalShown(true)}
                                data-attr="merge-person-button"
                                type="secondary"
                            >
                                Split IDs
                            </LemonButton>
                        )}
                    </div>
                }
            />

            <PersonDeleteModal />

            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => {
                    navigateToTab(tab as PersonsTabType)
                }}
                data-attr="persons-tabs"
                tabs={[
                    feedEnabled
                        ? {
                              key: PersonsTabType.FEED,
                              label: <span data-attr="persons-feed-tab">Feed</span>,
                              content: <PersonFeedCanvas person={person} />,
                          }
                        : false,
                    {
                        key: PersonsTabType.PROPERTIES,
                        label: <span data-attr="persons-properties-tab">Properties</span>,
                        content: (
                            <PropertiesTable
                                type={PropertyDefinitionType.Person}
                                properties={person.properties || {}}
                                searchable
                                onEdit={editProperty}
                                sortProperties
                                embedded={false}
                                onDelete={(key) => deleteProperty(key)}
                                filterable
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.EVENTS,
                        label: <span data-attr="persons-events-tab">Events</span>,
                        content: (
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    full: true,
                                    hiddenColumns: ['person'],
                                    source: {
                                        kind: NodeKind.EventsQuery,
                                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                                        personId: person.id,
                                        where: ["notEquals(event, '$exception')"],
                                        after: '-24h',
                                    },
                                }}
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.SESSION_RECORDINGS,
                        label: <span data-attr="person-session-recordings-tab">Recordings</span>,
                        content: (
                            <>
                                {!currentTeam?.session_recording_opt_in ? (
                                    <div className="mb-4">
                                        <LemonBanner type="info">
                                            Session recordings are currently disabled for this {settingLevel}. To use
                                            this feature, please go to your{' '}
                                            <Link
                                                to={`${urls.settings('project')}#recordings`}
                                                onClick={() => {
                                                    addProductIntentForCrossSell({
                                                        from: ProductKey.PERSONS,
                                                        to: ProductKey.SESSION_REPLAY,
                                                        intent_context: ProductIntentContext.PERSON_VIEW_RECORDINGS,
                                                    })
                                                }}
                                            >
                                                project settings
                                            </Link>{' '}
                                            and enable it.
                                        </LemonBanner>
                                    </div>
                                ) : null}
                                <div className="SessionRecordingPlaylistHeightWrapper">
                                    <SessionRecordingsPlaylist
                                        logicKey={`person-scene-${person.uuid}`}
                                        personUUID={person.uuid}
                                        distinctIds={person.distinct_ids}
                                        updateSearchParams
                                    />
                                </div>
                            </>
                        ),
                    },
                    {
                        key: PersonsTabType.EXCEPTIONS,
                        label: <span data-attr="persons-exceptions-tab">Exceptions</span>,
                        content: (
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    full: true,
                                    showEventFilter: false,
                                    hiddenColumns: ['person'],
                                    source: {
                                        kind: NodeKind.EventsQuery,
                                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                                        personId: person.id,
                                        event: '$exception',
                                        after: '-24h',
                                    },
                                }}
                            />
                        ),
                    },
                    {
                        key: PersonsTabType.COHORTS,
                        label: <span data-attr="persons-cohorts-tab">Cohorts</span>,
                        content: <PersonCohorts />,
                    },
                    groupsEnabled && person.uuid
                        ? {
                              key: PersonsTabType.RELATED,
                              label: (
                                  <span className="flex items-center" data-attr="persons-related-tab">
                                      Related groups
                                      <Tooltip title="People and groups that have shared events with this person in the last 90 days.">
                                          <IconInfo className="ml-1 text-base shrink-0" />
                                      </Tooltip>
                                  </span>
                              ),
                              content: <RelatedGroups id={person.uuid} groupTypeIndex={null} />,
                          }
                        : false,
                    person.uuid
                        ? {
                              key: PersonsTabType.SUMMARIES,
                              label: (
                                  <span className="flex items-center" data-attr="persons-related-tab">
                                      Summaries
                                      <Tooltip title="People and groups that have shared events with this person in the last 90 days.">
                                          <IconInfo className="ml-1 text-base shrink-0" />
                                      </Tooltip>
                                  </span>
                              ),
                              content: <PersonSummariesTable />,
                          }
                        : false,
                    person.uuid
                        ? {
                              key: PersonsTabType.FEATURE_FLAGS,
                              tooltip: `Only shows feature flags with targeting conditions based on person properties.`,
                              label: <span data-attr="persons-related-flags-tab">Feature flags</span>,
                              content: (
                                  <>
                                      <div className="flex deprecated-space-x-2 items-center mb-2">
                                          <div className="flex items-center">
                                              Choose ID:
                                              <Tooltip
                                                  title={
                                                      <div className="deprecated-space-y-2">
                                                          <div>
                                                              Feature flags values can depend on a person's distinct ID.
                                                          </div>
                                                          <div>
                                                              If you want your flag values to stay consistent for each
                                                              user, you can enable flag persistence in the feature flag
                                                              settings.
                                                          </div>
                                                          <div>
                                                              This option may depend on your specific setup and isn't
                                                              always suitable. Read more in the{' '}
                                                              <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps">
                                                                  documentation.
                                                              </Link>
                                                          </div>
                                                      </div>
                                                  }
                                              >
                                                  <IconInfo className="ml-1 text-base" />
                                              </Tooltip>
                                          </div>
                                          <LemonSelect
                                              value={distinctId || primaryDistinctId}
                                              onChange={(value) => value && setDistinctId(value)}
                                              options={person.distinct_ids.map((distinct_id) => ({
                                                  label: distinct_id,
                                                  value: distinct_id,
                                              }))}
                                              data-attr="person-feature-flags-select"
                                          />
                                      </div>
                                      <LemonDivider className="mb-4" />
                                      <RelatedFeatureFlags distinctId={distinctId || primaryDistinctId} />
                                  </>
                              ),
                          }
                        : false,
                    {
                        key: PersonsTabType.HISTORY,
                        label: 'History',
                        content: (
                            <ActivityLog
                                scope={ActivityScope.PERSON}
                                id={person.id}
                                caption={
                                    <LemonBanner type="info">
                                        This page only shows changes made by users in the PostHog site. Automatic
                                        changes from the API aren't shown here.
                                    </LemonBanner>
                                }
                            />
                        ),
                    },
                ]}
            />

            {splitMergeModalShown && person && <MergeSplitPerson person={person} />}
        </>
    )
}
