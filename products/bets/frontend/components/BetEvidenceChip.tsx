import { IconExternal, IconFlask, IconGraph, IconRewindPlay, IconWarning } from '@posthog/icons'
import { IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { BetsEvidenceApi, EvidenceKindEnumApi } from '../generated/api.schemas'

const EVIDENCE_KINDS: Record<EvidenceKindEnumApi, { label: string; color?: string; glyph: JSX.Element }> = {
    insight: { label: 'Insight', color: 'var(--color-product-product-analytics-light)', glyph: <IconGraph /> },
    chart: { label: 'Chart', color: 'var(--color-product-product-analytics-light)', glyph: <IconGraph /> },
    replay: { label: 'Session replay', color: 'var(--color-product-session-replay-light)', glyph: <IconRewindPlay /> },
    experiment: { label: 'Experiment', color: 'var(--color-product-experiments-light)', glyph: <IconFlask /> },
    error: { label: 'Error', color: 'var(--color-product-error-tracking-light)', glyph: <IconWarning /> },
    link: { label: 'Link', glyph: <IconExternal /> },
}

export function BetEvidenceChip({ evidence }: { evidence: BetsEvidenceApi }): JSX.Element {
    const kind = EVIDENCE_KINDS[evidence.kind] ?? EVIDENCE_KINDS.link
    const linked = !!evidence.url && !evidence.url.startsWith('chart:')
    const content = (
        <>
            <IconStack className="Bets__evidenceIcon shrink-0">
                <IconStackItem color={kind.color}>{kind.glyph}</IconStackItem>
            </IconStack>
            <span className="min-w-0 truncate">{evidence.label}</span>
        </>
    )
    return (
        <Tooltip>
            <TooltipTrigger
                delay={300}
                render={
                    linked ? (
                        <LinkPrimitive
                            to={evidence.url}
                            className="Bets__evidence inline-flex h-7 min-w-0 items-center gap-1.5"
                            data-attr={`bets-idea-evidence-${evidence.kind}`}
                        />
                    ) : (
                        <span
                            tabIndex={0}
                            className="Bets__evidence Bets__evidence--static inline-flex h-7 min-w-0 items-center gap-1.5"
                        />
                    )
                }
            >
                {content}
            </TooltipTrigger>
            <TooltipContent>
                <span className="flex flex-col">
                    <span className="opacity-70">{kind.label}</span>
                    <span>{evidence.label}</span>
                </span>
            </TooltipContent>
        </Tooltip>
    )
}
