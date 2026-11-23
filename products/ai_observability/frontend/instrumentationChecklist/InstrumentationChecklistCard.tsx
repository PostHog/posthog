import { useActions, useValues } from 'kea'

import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { InstrumentationCheckStatusEnumApi } from '../generated/api.schemas'
import { InstrumentationCheckRow } from '../redesign/shared/components/InstrumentationCheckRow'
import {
    INSTRUMENTATION_REFRESH_FAILED,
    InstrumentationRefreshButton,
} from '../redesign/shared/components/InstrumentationRefreshButton'
import { InstrumentationChecklistCardState, instrumentationChecklistLogic } from './instrumentationChecklistLogic'

const PANEL_KEY = 'instrumentation-checklist'

const STATE_SUMMARIES: Record<Exclude<InstrumentationChecklistCardState, 'hidden' | 'warnings'>, string> = {
    checking: 'Checking your events',
    collecting: 'Still collecting data',
    passing: 'No checks need attention',
}

/**
 * Tells a project which AI observability features its instrumentation leaves dark, at the top of
 * the tab people land on.
 *
 * How loud it is comes from `checklistCardState`. Warnings expand on landing; everything else
 * collapses to its header but stays expandable, because a checklist nobody can find is one nobody
 * can use to confirm a fix landed. Rendering nothing is reserved for having no verdict at all: the
 * flag is off, or the read failed and we would otherwise be guessing.
 *
 * The first read holds the header rather than a skeleton. It can take seconds on a project with a
 * lot of events, and a card that keeps its place and its name for that long reads as working, where
 * a shimmer of the same length reads as stuck.
 */
export function InstrumentationChecklistCard(): JSX.Element | null {
    const { checklistLoading, checklistBusy, checks, checklistCardState, windowDays, pendingCheckKey, refreshFailed } =
        useValues(instrumentationChecklistLogic)
    const { loadInstrumentationChecklist, dismissCheck, restoreCheck } = useActions(instrumentationChecklistLogic)

    if (checklistCardState === 'hidden') {
        return null
    }

    const isChecking = checklistCardState === 'checking'
    const warningCount = checks.filter((check) => check.status === InstrumentationCheckStatusEnumApi.Warning).length

    return (
        <div className="mb-4" data-attr="ai-observability-instrumentation-checklist">
            <LemonCollapse
                // LemonCollapse reads defaultActiveKey once, at mount. The card is already on screen
                // while the first read runs, so the verdict has to remount it or warnings land in a
                // panel that stays shut.
                key={isChecking ? 'checking' : 'graded'}
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
                                            {STATE_SUMMARIES[checklistCardState]}
                                        </span>
                                    )}
                                </div>
                            ),
                        },
                        // Nothing to expand into until the first read answers.
                        content: isChecking ? null : (
                            <div className="flex flex-col gap-3">
                                {checks.map((check) => (
                                    <InstrumentationCheckRow
                                        key={check.key}
                                        check={check}
                                        pendingCheckKey={pendingCheckKey}
                                        busy={checklistBusy}
                                        onDismiss={dismissCheck}
                                        onRestore={restoreCheck}
                                    />
                                ))}
                                <div className="flex items-center justify-between gap-2 border-t pt-3">
                                    {refreshFailed ? (
                                        <span className="text-danger text-xs">{INSTRUMENTATION_REFRESH_FAILED}</span>
                                    ) : (
                                        <span className="text-muted text-xs">
                                            Checked over the last {windowDays} days.
                                        </span>
                                    )}
                                    <InstrumentationRefreshButton
                                        refreshing={checklistLoading}
                                        refreshFailed={refreshFailed}
                                        pendingCheckKey={pendingCheckKey}
                                        onRefresh={() => loadInstrumentationChecklist({ refresh: true })}
                                        size="xsmall"
                                        data-attr="ai-observability-instrumentation-checklist-refresh"
                                    />
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
