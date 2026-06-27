import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonMenu, LemonTable, LemonTableColumns, LemonTag, type LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { SDK_DOCS_LINKS, SDK_TYPE_READABLE_NAME } from './sdkConstants'
import { AugmentedTeamSdkVersionsInfoRelease, type SdkType, sdkHealthLogic } from './sdkHealthLogic'

// The status badge is informational, not an action — it surfaces the version's age and upgrade
// suggestion. The tip shows on hover, but hover doesn't exist on touch and people tap the badge
// expecting a response, so a tap/click pins the same tip open (outside-click or Escape closes it).
function SdkStatusBadge({ type, label, reason }: { type: LemonTagType; label: string; reason: string }): JSX.Element {
    const [pinned, setPinned] = useState(false)
    const containerRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (!pinned) {
            return
        }
        const onPointerDown = (event: MouseEvent): void => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setPinned(false)
            }
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                setPinned(false)
            }
        }
        document.addEventListener('mousedown', onPointerDown)
        document.addEventListener('keydown', onKeyDown)
        return () => {
            document.removeEventListener('mousedown', onPointerDown)
            document.removeEventListener('keydown', onKeyDown)
        }
    }, [pinned])

    return (
        <span ref={containerRef} className="shrink-0">
            {/* `pinned || undefined` keeps native hover/focus when not pinned, and forces open on tap. */}
            <Tooltip placement="right" title={reason} visible={pinned || undefined}>
                <LemonTag type={type} className="cursor-help" onClick={() => setPinned((prev) => !prev)}>
                    {label}
                </LemonTag>
            </Tooltip>
        </span>
    )
}

// The version drill-in SQL and Activity page URL are computed by the backend (sql_query /
// activity_page_url on each release) so the UI and the SDK Health MCP tool stay in lockstep.
const COLUMNS: LemonTableColumns<AugmentedTeamSdkVersionsInfoRelease> = [
    {
        title: (
            <span>
                VERSION{' '}
                <Tooltip
                    title={
                        <>
                            Click on a version number to view events captured.
                            <br />
                            Hover over status for version age and/or suggestion.
                        </>
                    }
                >
                    <IconInfo />
                </Tooltip>
            </span>
        ),
        dataIndex: 'version',
        render: function RenderVersion(_, record) {
            return (
                <div className="flex items-center gap-2 justify-start">
                    <LemonMenu
                        items={[
                            {
                                label: 'Events on Activity page',
                                disabledReason: record.activityPageUrl ? undefined : 'Unavailable for this version',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'activity_page',
                                    })
                                    newInternalTab(record.activityPageUrl)
                                },
                            },
                            {
                                label: 'SQL query',
                                disabledReason: record.sqlQuery ? undefined : 'Unavailable for this version',
                                onClick: () => {
                                    posthog.capture('sdk doctor view events', {
                                        sdkType: record.type,
                                        destination: 'sql_editor',
                                    })
                                    newInternalTab(urls.sqlEditor({ query: record.sqlQuery }))
                                },
                            },
                        ]}
                    >
                        <code className="text-xs font-mono bg-muted-highlight rounded-sm cursor-pointer hover:bg-muted">
                            {record.version}
                        </code>
                    </LemonMenu>
                    {record.isOutdated ? (
                        <SdkStatusBadge type="danger" label="Outdated" reason={record.statusReason} />
                    ) : record.isCurrentOrNewer ? (
                        <SdkStatusBadge type="success" label="Current" reason={record.statusReason} />
                    ) : (
                        <SdkStatusBadge type="warning" label="Recent" reason={record.statusReason} />
                    )}
                </div>
            )
        },
    },
    {
        title: (
            <span>
                LAST EVENT{' '}
                <Tooltip title="This gets refreshed every night, click 'Scan Events' to refresh manually">
                    <IconInfo />
                </Tooltip>
            </span>
        ),
        dataIndex: 'maxTimestamp',
        render: function RenderMaxTimestamp(_, record) {
            return <TZLabel time={record.maxTimestamp} />
        },
    },
    {
        title: '# events, last 7 days',
        dataIndex: 'count',
        render: function RenderCount(_, record) {
            return <div className="text-xs text-muted-alt">{record.count}</div>
        },
    },
]

export function SdkSection({ sdkType }: { sdkType: SdkType }): JSX.Element {
    const { augmentedData, reportLoading: loading } = useValues(sdkHealthLogic)

    const sdk = augmentedData[sdkType]!
    const links = SDK_DOCS_LINKS[sdkType]
    const sdkName = SDK_TYPE_READABLE_NAME[sdkType]

    return (
        <div className="flex flex-col mb-4 p-2">
            <div className="flex flex-row justify-between items-center gap-2 mb-4">
                <div>
                    <h3 className="mb-0">{sdkName}</h3>
                    <Tooltip
                        title={
                            <>
                                Version number cached once a day.
                                <br />
                                Click 'Releases ↗' to check for any since.
                            </>
                        }
                    >
                        <small className="cursor-help">Latest version available: {sdk.currentVersion}</small>
                    </Tooltip>
                </div>

                <div className="flex flex-row gap-2">
                    <Link to={links.releases} target="_blank" targetBlankIcon>
                        Releases
                    </Link>
                    <Link to={links.docs} target="_blank" targetBlankIcon>
                        Docs
                    </Link>
                    <Link
                        to="https://posthog.com/docs/sdk-doctor/keeping-sdks-current#ways-to-keep-sdk-versions-current"
                        target="_blank"
                        targetBlankIcon
                    >
                        Updating
                    </Link>
                </div>
            </div>

            <LemonTable
                dataSource={sdk.allReleases}
                loading={loading}
                columns={COLUMNS}
                size="small"
                emptyState="No SDK information found. Try scanning recent events."
            />
        </div>
    )
}
