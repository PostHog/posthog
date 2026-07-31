import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTag, type LemonTagType } from 'lib/lemon-ui/LemonTag'
import { safeHttpUrl } from 'scenes/inbox/utils/reportPresentation'

import type {
    PgAnalyzeIssueReferenceApi,
    PgAnalyzeIssueSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to a pganalyze issue payload. */
export function isPgAnalyzeExtra(value: unknown): value is Record<string, unknown> & PgAnalyzeIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'references' in extra && Array.isArray(extra.references) && 'synced_at' in extra
}

/** Maps a pganalyze severity to a LemonTag tone. Case-insensitive; unknown values fall back to `default`. */
function severityTone(severity: string): LemonTagType {
    switch (severity.toLowerCase()) {
        case 'critical':
            return 'danger'
        case 'high':
            return 'caution'
        case 'medium':
            return 'warning'
        case 'low':
            return 'muted'
        case 'info':
            return 'completion'
        default:
            return 'default'
    }
}

/** Sentence-cases a label (first letter upper, rest lower). */
function sentenceCase(value: string): string {
    return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
}

function ReferenceRow({ reference }: { reference: PgAnalyzeIssueReferenceApi }): JSX.Element | null {
    if (reference.name === null && reference.url === null && reference.queryText === null) {
        return null
    }

    if (reference.name !== null) {
        const href = reference.url !== null ? safeHttpUrl(reference.url) : null
        return (
            <div className="flex items-center gap-1.5 text-xs flex-wrap">
                {reference.kind !== null && <span className="text-tertiary">{reference.kind}</span>}
                {href !== null ? (
                    <Link to={href} target="_blank" className="flex items-center gap-1 font-mono">
                        {reference.name} <IconExternal className="size-3" />
                    </Link>
                ) : (
                    <span className="font-mono">{reference.name}</span>
                )}
            </div>
        )
    }

    if (reference.queryText !== null) {
        return (
            <CodeSnippet language={Language.SQL} wrap compact maxLinesWithoutExpansion={6}>
                {reference.queryText}
            </CodeSnippet>
        )
    }

    return null
}

export function PgAnalyzeSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & PgAnalyzeIssueSignalExtraApi

    const serverLabel = extra.server_name ?? extra.server_human_id
    const metaChips = (
        <>
            {extra.severity !== null && (
                <LemonTag type={severityTone(extra.severity)}>{sentenceCase(extra.severity)}</LemonTag>
            )}
            {serverLabel && <LemonTag type="muted">{serverLabel}</LemonTag>}
        </>
    )

    const visibleReferences = extra.references.filter(
        (reference) => reference.name !== null || reference.url !== null || reference.queryText !== null
    )

    const externalUrl = extra.references
        .map((reference) => (reference.url !== null ? safeHttpUrl(reference.url) : null))
        .find((url): url is string => url !== null)

    return (
        <ExternalSignalCard
            signal={signal}
            metaChips={metaChips}
            footerLeft={
                <span className="flex items-center gap-1">
                    Synced <TZLabel time={extra.synced_at} />
                </span>
            }
            link={externalUrl ? { to: externalUrl, label: 'View in pganalyze' } : undefined}
        >
            <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                {signal.content}
            </LemonMarkdown>

            {visibleReferences.length > 0 && (
                <div className="border-t pt-2 mt-2 flex flex-col gap-2">
                    <div className="text-xs font-medium text-tertiary">References</div>
                    {visibleReferences.map((reference, index) => (
                        <ReferenceRow key={index} reference={reference} />
                    ))}
                </div>
            )}
        </ExternalSignalCard>
    )
}

export const pgAnalyzeSignalCardEntry: SignalCardEntry = {
    key: 'pganalyze',
    matches: (signal) => signal.source_product === 'pganalyze' && isPgAnalyzeExtra(signal.extra),
    Component: PgAnalyzeSignalCard,
}
