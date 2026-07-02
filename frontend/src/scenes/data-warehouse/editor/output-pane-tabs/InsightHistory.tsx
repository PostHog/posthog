import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconRevert } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SkeletonLog } from 'lib/components/ActivityLog/ActivityLog'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils'

import { QueryBasedInsightModel } from '~/types'

import { OutputTab, outputPaneLogic } from '../outputPaneLogic'
import { sqlEditorLogic, toDataVisualizationNode } from '../sqlEditorLogic'
import { InsightQueryVersion, insightHistoryLogic } from './insightHistoryLogic'

interface VersionRowShellProps {
    createdAt: string
    authorName: string
    email?: string | null
    isSystem?: boolean
    tags?: JSX.Element
    onRestore?: () => void
    children: React.ReactNode
}

function VersionRowShell({
    createdAt,
    authorName,
    email,
    isSystem,
    tags,
    onRestore,
    children,
}: VersionRowShellProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    return (
        <div className={clsx('flex flex-col rounded border', isExpanded ? 'border-primary' : 'border-transparent')}>
            <div
                className="flex items-center gap-3 px-2 py-2 rounded cursor-pointer hover:bg-surface-secondary group"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex-grow min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="font-semibold">
                            <TZLabel time={createdAt} formatDate="MMMM D" formatTime="h:mm A" />
                        </span>
                        {tags}
                    </div>
                    <div className="flex items-center gap-1.5 text-secondary text-xs mt-0.5">
                        <ProfilePicture
                            showName={false}
                            user={{
                                first_name: isSystem ? authorName : undefined,
                                email: email ?? undefined,
                            }}
                            type={isSystem ? 'system' : 'person'}
                            size="xs"
                        />
                        <span>{authorName}</span>
                    </div>
                </div>
                {onRestore && (
                    <LemonButton
                        size="small"
                        icon={<IconRevert />}
                        className="opacity-0 group-hover:opacity-100"
                        tooltip="Load this version into the editor to review and restore"
                        data-attr="sql-editor-insight-history-restore"
                        onClick={(e) => {
                            e.stopPropagation()
                            onRestore()
                        }}
                    >
                        Restore
                    </LemonButton>
                )}
            </div>
            {isExpanded && <div className="px-2 pb-2">{children}</div>}
        </div>
    )
}

function EditVersionRow({ version, isCurrent }: { version: InsightQueryVersion; isCurrent: boolean }): JSX.Element {
    const { setSuggestedQueryInput } = useActions(sqlEditorLogic)
    const { setActiveTab } = useActions(outputPaneLogic)

    return (
        <VersionRowShell
            createdAt={version.createdAt}
            authorName={version.authorName}
            email={version.email}
            isSystem={version.isSystem}
            tags={
                isCurrent ? (
                    <LemonTag type="primary" size="small">
                        Current version
                    </LemonTag>
                ) : undefined
            }
            onRestore={
                isCurrent
                    ? undefined
                    : () => {
                          setSuggestedQueryInput(version.afterSql, 'query_history')
                          setActiveTab(OutputTab.Results)
                      }
            }
        >
            <div className="text-xs text-secondary mb-1">Changes compared to the previous version</div>
            <SqlDiffViewer before={version.beforeSql} after={version.afterSql} />
        </VersionRowShell>
    )
}

function OriginalVersionRow({
    insight,
    sql,
    isCurrent,
}: {
    insight: QueryBasedInsightModel
    sql: string
    isCurrent: boolean
}): JSX.Element {
    const { setSuggestedQueryInput } = useActions(sqlEditorLogic)
    const { setActiveTab } = useActions(outputPaneLogic)

    return (
        <VersionRowShell
            createdAt={insight.created_at}
            authorName={insight.created_by ? fullName(insight.created_by) : 'Unknown'}
            email={insight.created_by?.email}
            tags={
                <>
                    <LemonTag size="small">Original</LemonTag>
                    {isCurrent && (
                        <LemonTag type="primary" size="small">
                            Current version
                        </LemonTag>
                    )}
                </>
            }
            onRestore={
                isCurrent
                    ? undefined
                    : () => {
                          setSuggestedQueryInput(sql, 'query_history')
                          setActiveTab(OutputTab.Results)
                      }
            }
        >
            <CodeSnippet language={Language.SQL} compact>
                {sql}
            </CodeSnippet>
        </VersionRowShell>
    )
}

function SqlDiffViewer({ before, after }: { before: string; after: string }): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)
    return (
        <div ref={containerRef} className="flex flex-col w-full">
            <MonacoDiffEditor
                original={before}
                modified={after}
                language="hogQL"
                width={width}
                options={{
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    renderGutterMenu: false,
                    scrollbar: {
                        alwaysConsumeMouseWheel: false,
                    },
                }}
            />
        </div>
    )
}

export function InsightHistory({ insight }: { insight: QueryBasedInsightModel | null }): JSX.Element {
    return insight ? (
        <InsightHistoryContent insight={insight} />
    ) : (
        // The insight itself is still loading — the tab shows immediately, the content follows
        <InsightHistorySkeleton />
    )
}

function InsightHistorySkeleton(): JSX.Element {
    return (
        <div className="deprecated-space-y-2 p-2">
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
        </div>
    )
}

function InsightHistoryContent({ insight }: { insight: QueryBasedInsightModel }): JSX.Element {
    const logic = insightHistoryLogic({ insightId: insight.id })
    const { versions, activityLoading } = useValues(logic)

    if (activityLoading) {
        return <InsightHistorySkeleton />
    }

    // The state the insight was created with: what the oldest recorded edit started from,
    // or the current query if the SQL has never been edited
    const originalSql = versions.length
        ? versions[versions.length - 1].beforeSql
        : (toDataVisualizationNode(insight.query)?.source.query ?? '')

    return (
        <div className="flex flex-col gap-1 p-2 max-w-200">
            {versions.map((version, index) => (
                <EditVersionRow key={version.id ?? index} version={version} isCurrent={index === 0} />
            ))}
            {originalSql.trim() !== '' && (
                <OriginalVersionRow insight={insight} sql={originalSql} isCurrent={versions.length === 0} />
            )}
        </div>
    )
}
