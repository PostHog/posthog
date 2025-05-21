import { SceneExport } from 'scenes/sceneTypes'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { LemonTable } from '@posthog/lemon-ui'
import { LemonTag } from '@posthog/lemon-ui'
import { LemonBanner } from '@posthog/lemon-ui'
import { LemonDivider } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'
import { IconAIText, IconChevronDown, IconTarget } from '@posthog/icons'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import React from 'react'

export const scene: SceneExport = {
    component: SessionSummaries,
}

type Tab = 'person' | 'funnel' | 'recording' | 'group' | 'settings'

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
    personId: string
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
            personId: 'user_123',
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
            personId: 'user_456',
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
            personId: 'user_789',
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
    ]

    return (
        <LemonTable
            dataSource={sampleData}
            columns={[
                {
                    title: 'Person ID',
                    dataIndex: 'personId',
                    width: 120,
                },
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
                                Person's Sessions Analysis
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

export function SessionSummaries(): JSX.Element {
    const [tab, setTab] = useState<Tab>('person')

    return (
        <div className="flex flex-col gap-4">
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setTab(newTab as Tab)}
                tabs={[
                    { key: 'person', label: 'Person summaries' },
                    { key: 'funnel', label: 'Funnel summaries' },
                    { key: 'recording', label: 'Recording summaries' },
                    { key: 'group', label: 'Group summaries' },
                    { key: 'settings', label: 'Settings' },
                ]}
            />
            <div>
                {tab === 'person' && <PersonSummariesTable />}
                {tab === 'funnel' && <div>Funnel summaries content</div>}
                {tab === 'recording' && <div>Recording summaries content</div>}
                {tab === 'group' && <div>Group summaries content</div>}
                {tab === 'settings' && <div>Settings content</div>}
            </div>
        </div>
    )
}
