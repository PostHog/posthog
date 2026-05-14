import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown, IconCopy, IconDownload, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { deploymentLogsLogic, DeploymentLogsLogicProps } from '../deploymentLogsLogic'
import { DeploymentStatus } from '../fixtures'
import type { DeploymentLogEntryApi } from '../generated/api.schemas'

const LEVEL_CHIPS: ReadonlyArray<{ value: string; label: string; tagType: 'default' | 'warning' | 'danger' }> = [
    { value: 'info', label: 'Info', tagType: 'default' },
    { value: 'warn', label: 'Warn', tagType: 'warning' },
    { value: 'error', label: 'Error', tagType: 'danger' },
]

const STEP_CHIPS: ReadonlyArray<{ value: string; label: string }> = [
    { value: 'clone', label: 'Clone' },
    { value: 'install', label: 'Install' },
    { value: 'build', label: 'Build' },
    { value: 'publish', label: 'Publish' },
]

function classForLevel(level: string | null): string {
    switch (level) {
        case 'error':
            return 'text-danger'
        case 'warn':
            return 'text-warning'
        default:
            return ''
    }
}

function formatRowAsText(row: DeploymentLogEntryApi): string {
    const ts = row.timestamp ?? ''
    const step = row.step ?? '-'
    const level = row.level ?? '-'
    return `${ts}  ${step}  ${level}  ${row.line ?? ''}`
}

function emptyStateMessage(status: DeploymentStatus): string {
    switch (status) {
        case 'queued':
        case 'initializing':
            return 'Waiting for the build worker to pick up this deployment…'
        case 'building':
            return "Build hasn't produced any log lines yet — they'll appear here as they stream in."
        default:
            return 'This deployment finished without producing log lines.'
    }
}

interface DeploymentLogsViewerProps {
    projectId: string
    deploymentId: string
    status: DeploymentStatus
}

export function DeploymentLogsViewer({ projectId, deploymentId, status }: DeploymentLogsViewerProps): JSX.Element {
    const logicProps: DeploymentLogsLogicProps = { projectId, deploymentId, status }
    return (
        <BindLogic logic={deploymentLogsLogic} props={logicProps}>
            <DeploymentLogsViewerContent {...logicProps} />
        </BindLogic>
    )
}

function DeploymentLogsViewerContent({ status, deploymentId }: DeploymentLogsLogicProps): JSX.Element {
    const {
        rawRows,
        filteredRows,
        hasMore,
        rowLimit,
        levelFilters,
        stepFilters,
        search,
        followTail,
        isLive,
        logsResponseLoading,
        logsResponse,
        logsError,
        lastFetchedAt,
        hasActiveFilters,
    } = useValues(deploymentLogsLogic)
    const { loadLogs, toggleLevelFilter, toggleStepFilter, setSearch, setFollowTail, clearFilters } =
        useActions(deploymentLogsLogic)

    const listRef = useRef<HTMLDivElement | null>(null)

    // Auto-scroll to the bottom of the log when new lines arrive and the
    // user hasn't disabled follow-tail. We tie the effect to filteredRows
    // (not rawRows) so the scroll happens once filters have been applied,
    // not before — keeps the view pinned to the *visible* tail.
    useEffect(() => {
        if (!followTail || !listRef.current) {
            return
        }
        listRef.current.scrollTop = listRef.current.scrollHeight
    }, [followTail, filteredRows.length])

    const firstLoad = logsResponseLoading && logsResponse === null
    const showEmpty = !firstLoad && rawRows.length === 0
    const showFilteredEmpty = !firstLoad && rawRows.length > 0 && filteredRows.length === 0

    const onCopy = async (): Promise<void> => {
        const text = filteredRows.map(formatRowAsText).join('\n')
        await copyToClipboard(text, 'build log')
    }

    const onDownload = (): void => {
        const text = filteredRows.map(formatRowAsText).join('\n')
        const blob = new Blob([text], { type: 'text/plain' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `deployment-${deploymentId}.log`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex flex-col gap-1">
                    <h3 className="text-lg font-semibold m-0">Logs</h3>
                    <p className="text-secondary text-sm m-0">
                        Build output forwarded to PostHog as <code>$log</code> events, tagged with{' '}
                        <code>deployment_id</code>.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {isLive ? (
                        <LemonTag type="primary">
                            <span className="inline-flex items-center gap-1">
                                <span className="size-2 rounded-full bg-primary animate-pulse" />
                                Live
                            </span>
                        </LemonTag>
                    ) : lastFetchedAt ? (
                        <span className="text-xs text-secondary">
                            Last refreshed <TZLabel time={new Date(lastFetchedAt).toISOString()} />
                        </span>
                    ) : null}
                </div>
            </div>

            {hasMore && (
                <LemonBanner type="warning">
                    Showing the most recent {rowLimit.toLocaleString()} lines — older lines were truncated by the row
                    cap.
                </LemonBanner>
            )}

            <div className="flex flex-col gap-2 p-2 border rounded">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search lines…"
                        value={search}
                        onChange={(value) => setSearch(value)}
                        allowClear
                        prefix={<IconSearch />}
                        className="flex-1 min-w-60"
                    />
                    <LemonSwitch
                        bordered
                        size="small"
                        checked={followTail}
                        onChange={(checked) => setFollowTail(checked)}
                        label="Follow tail"
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconCopy />}
                        onClick={onCopy}
                        disabledReason={filteredRows.length === 0 ? 'No lines to copy' : undefined}
                    >
                        Copy
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconDownload />}
                        onClick={onDownload}
                        disabledReason={filteredRows.length === 0 ? 'No lines to download' : undefined}
                    >
                        Download
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => loadLogs()}
                        loading={logsResponseLoading}
                    >
                        Refresh
                    </LemonButton>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-secondary">Level:</span>
                    {LEVEL_CHIPS.map((chip) => {
                        const active = levelFilters.has(chip.value)
                        return (
                            <button
                                key={chip.value}
                                type="button"
                                onClick={() => toggleLevelFilter(chip.value)}
                                className={`inline-flex items-center rounded px-2 py-0.5 border transition-colors ${active ? 'bg-fill-primary border-primary' : 'border-border'}`}
                                data-attr={`deployment-logs-level-${chip.value}`}
                            >
                                <LemonTag type={chip.tagType} size="small">
                                    {chip.label}
                                </LemonTag>
                            </button>
                        )
                    })}
                    <span className="text-secondary ml-2">Step:</span>
                    {STEP_CHIPS.map((chip) => {
                        const active = stepFilters.has(chip.value)
                        return (
                            <button
                                key={chip.value}
                                type="button"
                                onClick={() => toggleStepFilter(chip.value)}
                                className={`inline-flex items-center rounded px-2 py-0.5 border transition-colors ${active ? 'bg-fill-primary border-primary' : 'border-border'}`}
                                data-attr={`deployment-logs-step-${chip.value}`}
                            >
                                <LemonTag type="default" size="small">
                                    {chip.label}
                                </LemonTag>
                            </button>
                        )
                    })}
                    {hasActiveFilters && (
                        <LemonButton size="xsmall" type="tertiary" onClick={() => clearFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                </div>
            </div>

            {logsError && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadLogs(),
                    }}
                >
                    We couldn't load build logs from the analytics store. The deployment is unaffected — only this view
                    is.
                </LemonBanner>
            )}

            {firstLoad ? (
                <div className="flex flex-col gap-2 p-3 border rounded bg-bg-3000">
                    {Array.from({ length: 6 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-4 w-full" />
                    ))}
                </div>
            ) : showEmpty ? (
                <div className="p-6 text-center text-secondary border rounded bg-bg-3000">
                    {emptyStateMessage(status)}
                </div>
            ) : (
                <>
                    <div
                        ref={listRef}
                        className="font-mono text-xs leading-relaxed border rounded bg-bg-3000 p-3 max-h-[60vh] overflow-y-auto ph-no-capture"
                        data-attr="deployment-logs-list"
                    >
                        {showFilteredEmpty ? (
                            <div className="text-center text-secondary py-6">
                                No log lines match the current filters.{' '}
                                <button type="button" onClick={() => clearFilters()} className="text-link underline">
                                    Clear filters
                                </button>
                            </div>
                        ) : (
                            filteredRows.map((row, idx) => <LogLine key={`${row.timestamp}-${idx}`} row={row} />)
                        )}
                    </div>
                    {!followTail && filteredRows.length > 0 && (
                        <div className="flex justify-end">
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconChevronDown />}
                                onClick={() => setFollowTail(true)}
                            >
                                Jump to latest
                            </LemonButton>
                        </div>
                    )}
                </>
            )}

            <div className="text-xs text-secondary">
                {filteredRows.length === rawRows.length
                    ? `Showing ${rawRows.length.toLocaleString()} ${rawRows.length === 1 ? 'line' : 'lines'}`
                    : `Showing ${filteredRows.length.toLocaleString()} of ${rawRows.length.toLocaleString()} lines`}
            </div>
        </div>
    )
}

function LogLine({ row }: { row: DeploymentLogEntryApi }): JSX.Element {
    const time = row.timestamp ? row.timestamp.slice(11, 23) : '—'
    const colorClass = classForLevel(row.level)
    return (
        <div className={`grid grid-cols-[7rem_5rem_3rem_1fr] gap-3 items-baseline py-0.5 ${colorClass}`.trimEnd()}>
            <span className="text-secondary tabular-nums">{time}</span>
            <span className="text-secondary truncate">{row.step ?? '—'}</span>
            <span className="uppercase text-secondary">{row.level ?? '—'}</span>
            <span className="whitespace-pre-wrap break-words">{row.line ?? ''}</span>
        </div>
    )
}
