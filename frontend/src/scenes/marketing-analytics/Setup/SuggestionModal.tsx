import { useValues } from 'kea'

import { IconMinus, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import type { ApplyOp, Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { buildApplyDiff, type DiffLine } from './applyDiff'
import { usePlatformLogo } from './SuggestionIcon'

/** Navigate-only ops change no config, so there's no diff to preview — the modal says
 * what will happen instead. */
const NAVIGATE_EXPLANATIONS: Record<string, (op: ApplyOp) => string> = {
    retry_sync: (op) =>
        `Starts a fresh sync of ${op.display_name} from the ad platform. It runs in the background and can take several minutes — the numbers here won't change immediately.`,
    retry_syncs: (op) => {
        const names = (op.sources as { display_name: string }[]).map((source) => source.display_name)
        return `Starts a fresh sync of ${names.join(', ')} — ${names.length} in total. Each runs in the background and can take several minutes, so the numbers here won't change immediately. One failing doesn't stop the others.`
    },
    open_sources_section: () =>
        'Takes you to Ad platforms & sources, where each platform has its own row. These need fixing one at a time — they share a symptom, not a single fix.',
    open_oauth: () =>
        'Opens the ad platform in a new tab to re-authorise PostHog. Spend stops updating until this is done, and nothing changes here until you finish there.',
    open_source_wizard: () =>
        'Opens the data warehouse source wizard in a new tab, with this platform preselected. Connecting it is what makes its spend available.',
    open_schemas: (op) =>
        `Opens ${op.display_name}'s Schemas tab in a new tab. Tick the missing table there and it starts importing on the next sync — no amount of retrying selects it for you.`,
    open_source_columns: (op) =>
        `Jumps to ${op.display_name} under Ad platforms & sources, where you pick which warehouse column holds spend, campaign and date. Only you know which column is which, so this one can't be applied for you.`,
    open_goal_editor: () => "Opens this goal's editor below, so you can point it at something that exists.",
    open_mapping_editor: () =>
        'Opens the campaign mapping editor with these values filled in. Choosing the wrong one attributes this traffic to the wrong spend, which is why it is not done automatically.',
    open_settings: () => 'Opens marketing analytics settings in a new tab.',
}

/** Only the destructive and the creative — everything else is an additive config edit
 * that the default "Apply change" describes honestly. */
const APPLY_LABEL: Record<string, string> = {
    delete_conversion_goal: 'Remove goal',
    create_conversion_goal: 'Create goal',
    remove_custom_source_mapping: 'Remove mapping',
    remove_campaign_name_mapping: 'Remove mapping',
}

function explanationFor(op: ApplyOp): ((op: ApplyOp) => string) | undefined {
    // `in` rather than a plain lookup: TS types a Record index as always-defined, so
    // `explain ? ... : ...` would be a constant-true branch.
    return op.op in NAVIGATE_EXPLANATIONS ? NAVIGATE_EXPLANATIONS[op.op] : undefined
}

/** Spelled out because a strikethrough and a minus sign are otherwise the whole signal
 * that a row is about to be deleted. */
const CHANGE_VERB: Record<DiffLine['change'], { label: string; className: string }> = {
    add: { label: 'Add', className: 'text-success' },
    remove: { label: 'Remove', className: 'text-danger' },
    update: { label: 'Change', className: 'text-secondary' },
}

function DiffRow({ line }: { line: DiffLine }): JSX.Element {
    const verb = CHANGE_VERB[line.change]
    return (
        <div className="flex items-start gap-2 py-1.5 border-b last:border-b-0">
            <span className="shrink-0 mt-0.5">
                {line.change === 'add' ? (
                    <IconPlus className="text-success" />
                ) : line.change === 'remove' ? (
                    <IconMinus className="text-danger" />
                ) : (
                    <span className="text-muted text-xs font-mono">~</span>
                )}
            </span>
            <div className="grow min-w-0">
                <div className="text-xs text-secondary">
                    <span className={`font-semibold ${verb.className}`}>{verb.label}</span>
                    {` · ${line.setting}`}
                    {line.subject ? ` · ${line.subject}` : ''}
                </div>
                <div className="font-mono text-sm break-all">
                    {line.change === 'update' ? (
                        <>
                            <span className="line-through text-muted">{line.before}</span>
                            <span className="mx-1.5 text-secondary">→</span>
                            <span>{line.after}</span>
                        </>
                    ) : (
                        <span className={line.change === 'remove' ? 'line-through text-muted' : undefined}>
                            {line.after}
                        </span>
                    )}
                </div>
            </div>
        </div>
    )
}

function DiffBlock({ lines }: { lines: DiffLine[] }): JSX.Element {
    return (
        <div>
            <h4 className="mb-1">This will change</h4>
            <div className="border rounded px-3 bg-bg-light">
                {lines.map((line, index) => (
                    <DiffRow key={index} line={line} />
                ))}
            </div>
        </div>
    )
}

function UrlFixBanner({ fix }: { fix: ApplyOp }): JSX.Element {
    return (
        <LemonBanner type="warning">
            A mapping works around the tagging, it doesn't fix it. The lasting fix is to tag the ad URLs with{' '}
            <code className="font-mono">
                utm_source={String(fix.expected_utm_source)}
                {fix.expected_utm_campaign ? `&utm_campaign=${String(fix.expected_utm_campaign)}` : ''}
            </code>{' '}
            in the platform.
        </LemonBanner>
    )
}

/** Review-then-apply. The before/after is computed from the same op the server will
 * execute, so the preview can't drift from the change. */
export function SuggestionModal({
    suggestion,
    batch,
    onClose,
    onConfirm,
    onConfirmBatch,
    isApplying,
}: {
    suggestion: Suggestion | null
    /** Non-empty when reviewing "apply all safe" rather than one row. */
    batch: Suggestion[]
    onClose: () => void
    onConfirm: (suggestion: Suggestion) => void
    onConfirmBatch: (suggestions: Suggestion[]) => void
    isApplying: boolean
}): JSX.Element | null {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    // Above the early returns below — hook order has to match on every render.
    const logo = usePlatformLogo(suggestion?.integration ?? null)

    if (batch.length) {
        const lines = batch.flatMap((item) =>
            item.apply ? buildApplyDiff(item.apply, marketingAnalyticsConfig).lines : []
        )
        return (
            <LemonModal
                isOpen
                onClose={onClose}
                title={`Apply ${batch.length} safe change${batch.length === 1 ? '' : 's'}`}
                description="High-confidence, reversible changes only. Anything needing a judgement call was left out."
                footer={
                    <>
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isApplying}
                            onClick={() => (lines.length ? onConfirmBatch(batch) : onClose())}
                        >
                            {lines.length ? `Apply ${lines.length} change${lines.length === 1 ? '' : 's'}` : 'Close'}
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-3 max-w-xl">
                    {lines.length ? (
                        <DiffBlock lines={lines} />
                    ) : (
                        <LemonBanner type="info">These are already applied — nothing would change.</LemonBanner>
                    )}
                    <ul className="text-sm text-secondary mb-0 pl-4 list-disc">
                        {batch.map((item) => (
                            <li key={item.id}>{item.title}</li>
                        ))}
                    </ul>
                </div>
            </LemonModal>
        )
    }

    if (!suggestion?.apply) {
        return null
    }

    const op = suggestion.apply
    const explain = explanationFor(op)
    const diff = explain ? null : buildApplyDiff(op, marketingAnalyticsConfig)
    const urlFix = suggestion.also_recommended.find((candidate) => candidate.op === 'fix_platform_urls')

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={
                logo ? (
                    <span className="flex items-center gap-2">
                        {logo}
                        {suggestion.title}
                    </span>
                ) : (
                    suggestion.title
                )
            }
            description={suggestion.evidence}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isApplying}
                        status={
                            suggestion.kind === 'remove_mapping' || op.op === 'delete_conversion_goal'
                                ? 'danger'
                                : undefined
                        }
                        // Applying a no-op would report "applied" and hand back an Undo
                        // that strips config the user already had.
                        onClick={() => (diff?.isNoop && !explain ? onClose() : onConfirm(suggestion))}
                    >
                        {explain ? 'Continue' : diff?.isNoop ? 'Close' : (APPLY_LABEL[op.op] ?? 'Apply change')}
                    </LemonButton>
                </>
            }
        >
            <div className="deprecated-space-y-3 max-w-xl">
                {explain ? (
                    <p className="mb-0">{explain(op)}</p>
                ) : diff?.isNoop ? (
                    <LemonBanner type="info">
                        This is already applied — nothing would change. It'll disappear from the list on the next scan.
                    </LemonBanner>
                ) : (
                    <DiffBlock lines={diff?.lines ?? []} />
                )}

                {urlFix ? <UrlFixBanner fix={urlFix} /> : null}
            </div>
        </LemonModal>
    )
}
