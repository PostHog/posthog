import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconClock, IconMinusSquare, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { InstrumentationCheckApi, InstrumentationCheckStatusEnumApi } from '../generated/api.schemas'
import { instrumentationChecklistLogic } from './instrumentationChecklistLogic'

const PANEL_KEY = 'instrumentation-checklist'
const BUSY_REASON = 'Wait for the current update to finish'

const STATUS_ICONS: Record<InstrumentationCheckStatusEnumApi, JSX.Element> = {
    [InstrumentationCheckStatusEnumApi.Ok]: <IconCheckCircle className="text-success shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Warning]: <IconWarning className="text-warning shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Pending]: <IconClock className="text-muted shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Dismissed]: <IconMinusSquare className="text-muted shrink-0 mt-0.5" />,
}

function InstrumentationCheckRow({ check }: { check: InstrumentationCheckApi }): JSX.Element {
    const { checklistBusy, pendingCheckKey } = useValues(instrumentationChecklistLogic)
    const { dismissCheck, restoreCheck } = useActions(instrumentationChecklistLogic)

    const isWarning = check.status === InstrumentationCheckStatusEnumApi.Warning
    const isDismissed = check.status === InstrumentationCheckStatusEnumApi.Dismissed
    const isWriting = pendingCheckKey === check.key

    return (
        <div className="flex items-start gap-2">
            {STATUS_ICONS[check.status]}
            <div className="flex-1 min-w-0">
                <div className={clsx('text-sm font-medium', isDismissed && 'text-muted')}>
                    {check.title}
                    {isDismissed ? (
                        <LemonTag type="muted" size="small" className="ml-2">
                            Not applicable
                        </LemonTag>
                    ) : null}
                </div>
                <div className="text-muted text-sm">
                    {check.detail}{' '}
                    {isWarning ? (
                        <Link to={check.docs_url} target="_blank" targetBlankIcon>
                            Learn more
                        </Link>
                    ) : null}
                </div>
            </div>
            {isWarning || isDismissed ? (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    className="shrink-0"
                    loading={isWriting}
                    disabledReason={checklistBusy && !isWriting ? BUSY_REASON : undefined}
                    onClick={() => (isDismissed ? restoreCheck(check.key) : dismissCheck(check.key))}
                    data-attr={
                        isDismissed
                            ? 'ai-observability-instrumentation-checklist-recheck'
                            : 'ai-observability-instrumentation-checklist-dismiss'
                    }
                >
                    {isDismissed ? 'Recheck' : 'Not applicable'}
                </LemonButton>
            ) : null}
        </div>
    )
}

/**
 * Tells a project which AI observability features its instrumentation leaves dark, at the top of
 * the tab people land on.
 *
 * How loud it is comes from `checklistCardState`. Warnings expand on landing; everything else
 * collapses to its header but stays expandable, because a checklist nobody can find is one nobody
 * can use to confirm a fix landed. Rendering nothing is reserved for having no verdict at all: the
 * flag is off, or the read failed and we would otherwise be guessing.
 */
export function InstrumentationChecklistCard(): JSX.Element | null {
    const {
        checklist,
        checklistLoading,
        checklistEnabled,
        checks,
        checklistCardState,
        windowDays,
        pendingCheckKey,
        refreshFailed,
    } = useValues(instrumentationChecklistLogic)
    const { loadInstrumentationChecklist } = useActions(instrumentationChecklistLogic)

    // Only the first read, so a dismissal does not replace the card the user just clicked in.
    if (checklistEnabled && checklist === null && checklistLoading) {
        return <LemonSkeleton className="h-10 w-full mb-4" />
    }

    if (checklistCardState === 'hidden') {
        return null
    }

    const warningCount = checks.filter((check) => check.status === InstrumentationCheckStatusEnumApi.Warning).length

    return (
        <div className="mb-4" data-attr="ai-observability-instrumentation-checklist">
            <LemonCollapse
                defaultActiveKey={checklistCardState === 'warnings' ? PANEL_KEY : undefined}
                panels={[
                    {
                        key: PANEL_KEY,
                        dataAttr: 'ai-observability-instrumentation-checklist-toggle',
                        header: {
                            children: (
                                <div className="flex w-full items-center gap-2">
                                    <span className="font-semibold">Instrumentation checklist</span>
                                    {checklistCardState === 'warnings' ? (
                                        <LemonTag type="warning" size="small">
                                            {warningCount === 1
                                                ? '1 check needs attention'
                                                : `${warningCount} checks need attention`}
                                        </LemonTag>
                                    ) : (
                                        <span className="text-muted font-normal">
                                            {checklistCardState === 'collecting'
                                                ? 'Still collecting data'
                                                : 'No checks need attention'}
                                        </span>
                                    )}
                                </div>
                            ),
                        },
                        content: (
                            <div className="flex flex-col gap-3">
                                {checks.map((check) => (
                                    <InstrumentationCheckRow key={check.key} check={check} />
                                ))}
                                <div className="flex items-center justify-between gap-2 border-t pt-3">
                                    {refreshFailed ? (
                                        <span className="text-danger text-xs">Could not refresh the checklist.</span>
                                    ) : (
                                        <span className="text-muted text-xs">
                                            Checked over the last {windowDays} days.
                                        </span>
                                    )}
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        icon={<IconRefresh />}
                                        loading={checklistLoading}
                                        disabledReason={pendingCheckKey !== null ? BUSY_REASON : undefined}
                                        onClick={() => loadInstrumentationChecklist()}
                                        data-attr="ai-observability-instrumentation-checklist-refresh"
                                    >
                                        {refreshFailed ? 'Try again' : 'Refresh'}
                                    </LemonButton>
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
