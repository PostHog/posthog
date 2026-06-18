import { IconLock } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { GithubIssueSignalExtra } from '~/queries/schema/schema-signals'

import { ExternalSignalCard, type StatePill } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to a GitHub issue payload. */
export function isGithubIssueExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & GithubIssueSignalExtra {
    return 'html_url' in extra && 'number' in extra
}

function titleCase(value: string): string {
    return value.length > 0 ? value[0].toUpperCase() + value.slice(1).toLowerCase() : value
}

function statePillFromState(state: string): StatePill {
    switch (state.toLowerCase()) {
        case 'open':
            return { label: 'Open', tone: 'success' }
        case 'closed':
            // Owner preference: closed reads as muted/gray rather than alarming.
            return { label: 'Closed', tone: 'muted' }
        default:
            return { label: titleCase(state), tone: 'default' }
    }
}

export function GithubIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & GithubIssueSignalExtra

    const labels = Array.isArray(extra.labels) ? extra.labels : []

    const metaChips = (
        <>
            {labels.map((label) => (
                <LemonTag key={label} size="small" className="rounded-full">
                    {label}
                </LemonTag>
            ))}
            {extra.locked && (
                <LemonTag size="small" type="muted" icon={<IconLock />}>
                    Locked
                </LemonTag>
            )}
        </>
    )

    const footerLeft = (
        <span>
            Opened {humanFriendlyDetailedTime(extra.created_at)}
            {extra.updated_at !== extra.created_at && ` · Updated ${humanFriendlyDetailedTime(extra.updated_at)}`}
        </span>
    )

    return (
        <ExternalSignalCard
            signal={signal}
            title={<span className="font-medium">#{extra.number}</span>}
            statePill={statePillFromState(extra.state)}
            metaChips={metaChips}
            footerLeft={footerLeft}
            link={{ to: extra.html_url, label: 'View on GitHub' }}
        >
            {signal.content}
        </ExternalSignalCard>
    )
}

export const githubIssueSignalCardEntry: SignalCardEntry = {
    key: 'github',
    matches: (signal) => signal.source_product === 'github' && isGithubIssueExtra(signal.extra),
    Component: GithubIssueSignalCard,
}
