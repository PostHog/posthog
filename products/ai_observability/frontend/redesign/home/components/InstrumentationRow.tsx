import { useState } from 'react'

import { IconChevronDown, IconCheckCircle, IconMinusSquare, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { cn } from 'lib/utils/css-classes'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../../../generated/api.schemas'

export interface InstrumentationRowProps {
    checklist: InstrumentationChecklistApi | null
    loading: boolean
    onDismiss: (key: AIObservabilityInstrumentationCheckEnumApi) => void
    onRestore: (key: AIObservabilityInstrumentationCheckEnumApi) => void
}

const { Ok, Warning, Dismissed } = InstrumentationCheckStatusEnumApi

function StatusIcon({ status }: { status: InstrumentationCheckStatusEnumApi }): JSX.Element {
    if (status === Warning) {
        return <IconWarning className="mt-0.5 shrink-0 text-warning" />
    }
    if (status === Ok) {
        return <IconCheckCircle className="mt-0.5 shrink-0 text-success" />
    }
    return <IconMinusSquare className="mt-0.5 shrink-0 text-muted" />
}

interface CheckItemProps {
    check: InstrumentationCheckApi
    disabled: boolean
    onDismiss: InstrumentationRowProps['onDismiss']
    onRestore: InstrumentationRowProps['onRestore']
}

function CheckItem({ check, disabled, onDismiss, onRestore }: CheckItemProps): JSX.Element {
    const dismissed = check.status === Dismissed

    return (
        <li className="flex items-start gap-2">
            <StatusIcon status={check.status} />
            <div className="min-w-0 flex-1">
                <div className={cn('text-sm font-medium', dismissed && 'text-muted')}>{check.title}</div>
                <div className="text-sm text-muted">
                    {check.detail}{' '}
                    <Link to={check.docs_url} target="_blank" targetBlankIcon>
                        Docs
                    </Link>
                </div>
            </div>
            {dismissed ? (
                // pinned: data-attr feeds autocapture, so dashboards and tests find the control by this value
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={disabled ? 'Wait for the update to finish' : undefined}
                    onClick={() => onRestore(check.key)}
                    data-attr={`home-instrumentation-restore-${check.key}`}
                >
                    Restore
                </LemonButton>
            ) : check.status === Warning ? (
                // pinned: data-attr feeds autocapture, so dashboards and tests find the control by this value
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={disabled ? 'Wait for the update to finish' : undefined}
                    onClick={() => onDismiss(check.key)}
                    data-attr={`home-instrumentation-dismiss-${check.key}`}
                >
                    Dismiss
                </LemonButton>
            ) : null}
        </li>
    )
}

export function InstrumentationRow({
    checklist,
    loading,
    onDismiss,
    onRestore,
}: InstrumentationRowProps): JSX.Element | null {
    // Purely visual, so it stays in the component. Null means the person has not chosen yet.
    const [chosenOpen, setChosenOpen] = useState<boolean | null>(null)

    if (!checklist) {
        return loading ? <LemonSkeleton className="h-10 w-full" /> : null
    }
    // A dismissed check counts as passing, so the row stays while one exists to keep Restore reachable.
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
                        Instrumentation {checklist.passing} of {checklist.total}
                    </span>
                </LemonButton>
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
            {open ? (
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {checklist.checks.map((check) => (
                        <CheckItem
                            key={check.key}
                            check={check}
                            disabled={loading}
                            onDismiss={onDismiss}
                            onRestore={onRestore}
                        />
                    ))}
                </ul>
            ) : null}
        </section>
    )
}
