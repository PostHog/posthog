/**
 * PROTOTYPE — THROWAWAY CODE, do not ship.
 *
 * Question: should the "You have an unsaved insight from <date>. Click here" text (ReloadInsight)
 * become an item in the saved-insights table below it?
 *
 * Three variants on the existing /insights route, switchable via `?variant=` or the floating
 * bottom bar (also ← / → keys):
 *   A — the draft is a pinned first row in the insights table (default)
 *   B — the draft is a strip above the table
 *   C — the draft is a dismissible banner (evolved status quo)
 *
 * Run `./bin/start` and open /insights. Caveats: everything is gated to local dev builds;
 * if no real draft exists in localStorage a sample draft is shown (labelled in the bottom bar);
 * "Discard" is stubbed with a toast so the demo draft survives; client-side column sorts can
 * move the pinned row in variant A.
 */
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { parseDraftQueryFromLocalStorage } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Node } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { AccessControlLevel } from '~/types'

import { QUERY_TYPES_METADATA } from './insightTypesMetadata'
import { SavedInsightListItem } from './savedInsightsLogic'

// 'development' only (not just "not production"): keeps Jest and Storybook snapshots untouched
const PROTOTYPE_ENABLED = process.env.NODE_ENV === 'development'

export type DraftPrototypeVariant = 'A' | 'B' | 'C'

export interface DraftQueryPayload {
    query: Node<Record<string, any>>
    timestamp: number
}

const VARIANTS: DraftPrototypeVariant[] = ['A', 'B', 'C']
const VARIANT_NAMES: Record<DraftPrototypeVariant, string> = {
    A: 'Row in the table',
    B: 'Strip above the table',
    C: 'Dismissible banner',
}

export const DRAFT_ROW_ID = -1

const SAMPLE_DRAFT_QUERY = {
    kind: 'InsightVizNode',
    source: {
        kind: 'TrendsQuery',
        series: [{ kind: 'EventsNode', event: '$pageview', name: '$pageview', math: 'total' }],
    },
} as unknown as Node<Record<string, any>>

function variantFromSearchParams(searchParams: Record<string, any>): DraftPrototypeVariant {
    const raw = String(searchParams.variant ?? 'A').toUpperCase()
    return (VARIANTS as string[]).includes(raw) ? (raw as DraftPrototypeVariant) : 'A'
}

function cycleVariant(delta: number): void {
    const current = variantFromSearchParams(router.values.searchParams)
    const next = VARIANTS[(VARIANTS.indexOf(current) + delta + VARIANTS.length) % VARIANTS.length]
    router.actions.replace(
        router.values.location.pathname,
        { ...router.values.searchParams, variant: next },
        router.values.hashParams
    )
}

function discardDraftStub(): void {
    lemonToast.info('Prototype: discard is stubbed so the draft stays around for the demo.')
}

export function isDraftRow(item: SavedInsightListItem): boolean {
    return item.id === DRAFT_ROW_ID
}

export function useDraftInsightPrototype(): {
    variant: DraftPrototypeVariant | null
    draft: DraftQueryPayload | null
    isSample: boolean
    draftRow: SavedInsightListItem | null
} {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { searchParams } = useValues(router)
    const sampleTimestamp = useMemo(() => Date.now() - 3 * 60 * 60 * 1000, [])

    if (!PROTOTYPE_ENABLED) {
        return { variant: null, draft: null, isSample: false, draftRow: null }
    }

    const stored = localStorage.getItem(`draft-query-${currentTeamId}`)
    const parsed = stored ? parseDraftQueryFromLocalStorage(stored) : null
    const isSample = !parsed?.query
    const draft: DraftQueryPayload = parsed?.query ? parsed : { query: SAMPLE_DRAFT_QUERY, timestamp: sampleTimestamp }

    const timestampIso = dayjs(draft.timestamp).toISOString()
    const draftRow = {
        id: DRAFT_ROW_ID,
        short_id: 'draft-prototype',
        name: '',
        query: draft.query,
        tags: [],
        favorited: false,
        created_by: user ?? null,
        created_at: timestampIso,
        last_modified_at: timestampIso,
        last_modified_by: null,
        last_viewed_at: null,
        updated_at: timestampIso,
        user_access_level: AccessControlLevel.Viewer,
        saved: false,
        deleted: false,
        is_sample: false,
        order: null,
        result: null,
        dashboards: null,
        dashboard_tiles: null,
    } as unknown as SavedInsightListItem

    return { variant: variantFromSearchParams(searchParams), draft, isSample, draftRow }
}

function DraftQueryIcon({
    query,
    className,
}: {
    query: Node<Record<string, any>>
    className?: string
}): JSX.Element | null {
    const kind = isNodeWithSource(query) ? query.source.kind : query.kind
    const Icon = QUERY_TYPES_METADATA[kind]?.icon
    return Icon ? <Icon className={className} /> : null
}

/** Variant A — name cell of the pinned draft row. */
export function DraftRowNameCellPrototype({ item }: { item: SavedInsightListItem }): JSX.Element {
    const summarizeInsight = useSummarizeInsight()
    return (
        <div className="flex items-center gap-1">
            <LemonTableLink
                to={urls.insightNew({ query: item.query ?? undefined })}
                title={
                    <span className="flex items-center gap-2">
                        <i>{summarizeInsight(item.query) || 'Unsaved insight'}</i>
                        <LemonTag type="warning" size="small">
                            Draft
                        </LemonTag>
                    </span>
                }
                description="Unsaved changes, only stored in this browser"
            />
        </div>
    )
}

/** Variant A — actions cell of the pinned draft row. */
export function DraftRowMoreMenuPrototype({ item }: { item: SavedInsightListItem }): JSX.Element {
    return (
        <More
            overlay={
                <>
                    <LemonButton to={urls.insightNew({ query: item.query ?? undefined })} fullWidth>
                        Continue editing
                    </LemonButton>
                    <LemonDivider />
                    <LemonButton status="danger" onClick={discardDraftStub} fullWidth>
                        Discard draft
                    </LemonButton>
                </>
            }
        />
    )
}

/** Variant B — a draft strip sitting between the filters and the table. */
export function DraftStripPrototype({ draft, isSample }: { draft: DraftQueryPayload; isSample: boolean }): JSX.Element {
    const summarizeInsight = useSummarizeInsight()
    return (
        <LemonCard hoverEffect={false} className="flex items-center gap-3 p-3 border-warning bg-warning-highlight">
            <DraftQueryIcon query={draft.query} className="text-secondary text-2xl shrink-0" />
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 font-semibold">
                    <span className="truncate">{summarizeInsight(draft.query) || 'Unsaved insight'}</span>
                    <LemonTag type="warning" size="small">
                        Draft
                    </LemonTag>
                </div>
                <div className="text-secondary text-xs">
                    Unsaved insight from <TZLabel time={dayjs(draft.timestamp)} />. Only stored in this browser
                    {isSample ? ' (sample)' : ''}.
                </div>
            </div>
            <LemonButton size="small" onClick={discardDraftStub}>
                Discard
            </LemonButton>
            <LemonButton size="small" type="primary" to={urls.insightNew({ query: draft.query })}>
                Continue editing
            </LemonButton>
        </LemonCard>
    )
}

/** Variant C — the current banner shape, upgraded with a proper action and dismiss. */
export function DraftBannerPrototype({ draft }: { draft: DraftQueryPayload }): JSX.Element {
    return (
        <LemonBanner
            type="info"
            onClose={discardDraftStub}
            action={{ children: 'Continue editing', to: urls.insightNew({ query: draft.query }) }}
        >
            You have an unsaved insight from <TZLabel time={dayjs(draft.timestamp)} />.
        </LemonBanner>
    )
}

/** Floating bottom-center bar to flip between variants. Hidden in production builds. */
export function PrototypeSwitcherBar({ note }: { note?: string }): JSX.Element | null {
    const { searchParams } = useValues(router)
    const variant = variantFromSearchParams(searchParams)

    useEffect(() => {
        if (!PROTOTYPE_ENABLED) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (event.key === 'ArrowLeft') {
                cycleVariant(-1)
            } else if (event.key === 'ArrowRight') {
                cycleVariant(1)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [])

    if (!PROTOTYPE_ENABLED) {
        return null
    }

    return (
        <div className="fixed bottom-4 left-1/2 z-[1000] flex -translate-x-1/2 items-center gap-1 rounded-full bg-black/85 px-2 py-1 text-white shadow-xl">
            <button
                type="button"
                aria-label="Previous variant"
                className="cursor-pointer rounded-full px-1.5 py-0.5 hover:bg-white/20"
                onClick={() => cycleVariant(-1)}
            >
                <IconChevronLeft />
            </button>
            <span className="px-1 text-xs font-semibold whitespace-nowrap">
                Prototype {variant} · {VARIANT_NAMES[variant]}
                {note ? <span className="font-normal text-white/70"> · {note}</span> : null}
            </span>
            <button
                type="button"
                aria-label="Next variant"
                className="cursor-pointer rounded-full px-1.5 py-0.5 hover:bg-white/20"
                onClick={() => cycleVariant(1)}
            >
                <IconChevronRight />
            </button>
        </div>
    )
}
