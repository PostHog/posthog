import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { cn } from 'lib/utils/css-classes'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../../../generated/api.schemas'
import { InstrumentationCheckRow } from '../../shared/components/InstrumentationCheckRow'
import {
    INSTRUMENTATION_REFRESH_FAILED,
    InstrumentationRefreshButton,
} from '../../shared/components/InstrumentationRefreshButton'

export interface InstrumentationRowProps {
    checklist: InstrumentationChecklistApi | null
    /** Whether the checklist is loading or saving. */
    loading: boolean
    /** The check whose dismissal or recheck is being saved, if any. */
    pendingCheckKey: AIObservabilityInstrumentationCheckEnumApi | null
    /** Whether the checklist is being read again. */
    refreshing: boolean
    /** Whether the last refresh failed under the checklist on screen. */
    refreshFailed: boolean
    onDismiss: (key: AIObservabilityInstrumentationCheckEnumApi) => void
    onRestore: (key: AIObservabilityInstrumentationCheckEnumApi) => void
    onRefresh: () => void
}

const { Ok, Warning } = InstrumentationCheckStatusEnumApi

export function InstrumentationRow({
    checklist,
    loading,
    pendingCheckKey,
    refreshing,
    refreshFailed,
    onDismiss,
    onRestore,
    onRefresh,
}: InstrumentationRowProps): JSX.Element | null {
    // Purely visual, so it stays in the component. Null means the person has not chosen yet.
    const [chosenOpen, setChosenOpen] = useState<boolean | null>(null)

    if (!checklist) {
        return loading ? <LemonSkeleton className="h-10 w-full" /> : null
    }
    // A dismissed check counts as passing, so the row stays while one exists to keep Recheck reachable.
    if (checklist.checks.every((check) => check.status === Ok)) {
        return null
    }

    const open = chosenOpen ?? checklist.checks.some((check) => check.status === Warning)

    return (
        // pinned: data-attrs feed autocapture; dashboards and tests find the row by these values
        <section
            className="flex min-w-0 flex-col gap-2 rounded border bg-surface-primary p-3"
            data-attr="home-instrumentation"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonButton
                    size="small"
                    type="tertiary"
                    sideIcon={<IconChevronDown className={cn(open && 'rotate-180')} />}
                    onClick={() => setChosenOpen(!open)}
                    aria-expanded={open}
                    data-attr="home-instrumentation-toggle"
                >
                    <span className="font-semibold">
                        Instrumentation <span translate="no">{checklist.passing}</span> of{' '}
                        <span translate="no">{checklist.total}</span>
                    </span>
                </LemonButton>
                <div className="flex flex-wrap items-center gap-2">
                    {refreshFailed ? (
                        <span className="text-danger text-xs">{INSTRUMENTATION_REFRESH_FAILED}</span>
                    ) : null}
                    <InstrumentationRefreshButton
                        refreshing={refreshing}
                        refreshFailed={refreshFailed}
                        pendingCheckKey={pendingCheckKey}
                        onRefresh={onRefresh}
                        size="small"
                        data-attr="home-instrumentation-refresh"
                    />
                    {checklist.agent_prompt !== null ? (
                        <AgentPromptButton
                            appearance="lemon"
                            label="Fix instrumentation"
                            actions={[
                                {
                                    key: 'ai-observability-instrumentation',
                                    label: 'Fix instrumentation',
                                    buildPrompt: () => checklist.agent_prompt ?? '',
                                },
                            ]}
                            data-attr="home-instrumentation-prompt"
                        />
                    ) : null}
                </div>
            </div>
            {open ? (
                <div className="flex flex-col gap-3">
                    {checklist.checks.map((check) => (
                        <InstrumentationCheckRow
                            key={check.key}
                            check={check}
                            pendingCheckKey={pendingCheckKey}
                            busy={loading}
                            onDismiss={onDismiss}
                            onRestore={onRestore}
                        />
                    ))}
                </div>
            ) : null}
        </section>
    )
}
