import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { ApplyOp, Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { CAPABILITY_COPY } from './ReadinessHeader'
import { SECTION_BY_KIND, SECTION_LABEL } from './sectionRouting'
import { SuggestionIcon } from './SuggestionIcon'

function findOp(ops: ApplyOp[], op: string): ApplyOp | undefined {
    return ops.find((candidate) => candidate.op === op)
}

const CTA_LABEL: Record<string, string> = {
    retry_sync: 'Retry sync',
    retry_syncs: 'Retry all',
    open_sources_section: 'Go to sources',
    open_oauth: 'Reconnect',
    open_source_wizard: 'Connect',
    open_schemas: 'Select tables',
    open_source_columns: 'Map columns',
    open_goal_editor: 'Fix goal',
    open_mapping_editor: 'Choose',
    open_settings: 'Open settings',
}

/** Advice, never an apply button — the mapping is the workaround, retagging the ad URL
 * is the fix. */
function UrlFixHint({ fix }: { fix: ApplyOp }): JSX.Element {
    const expectedSource = fix.expected_utm_source as string
    const expectedCampaign = fix.expected_utm_campaign as string
    const snippet = [
        expectedSource ? `utm_source=${expectedSource}` : null,
        expectedCampaign ? `utm_campaign=${expectedCampaign}` : null,
    ]
        .filter(Boolean)
        .join('&')

    if (!snippet) {
        return (
            <span className="text-xs text-secondary">
                Better fix: tag the ad URLs in the platform so the UTM values match.
            </span>
        )
    }

    return (
        <div className="flex items-center gap-2 text-xs text-secondary">
            <span>Better fix — tag the ad URLs with</span>
            <code className="font-mono">{snippet}</code>
            <LemonButton size="xsmall" type="tertiary" onClick={() => void copyToClipboard(snippet, 'UTM parameters')}>
                Copy
            </LemonButton>
        </div>
    )
}

export function SuggestionRow({
    suggestion,
    onReview,
    isDismissed = false,
    currentSection,
}: {
    suggestion: Suggestion
    onReview: (suggestion: Suggestion) => void
    /** Set when the row is rendered inside a section, so it doesn't offer to send you
     * where you already are. */
    currentSection?: SetupSection
    /** Set inside the hidden list, which swaps Dismiss for Restore. */
    isDismissed?: boolean
}): JSX.Element {
    const { applyingIds } = useValues(setupPlanLogic)
    const { dismissSuggestion, restoreSuggestion } = useActions(setupPlanLogic)
    const { setSetupSection } = useActions(marketingAnalyticsLogic)

    const isApplying = applyingIds.includes(suggestion.id)
    const urlFix = findOp(suggestion.also_recommended, 'fix_platform_urls')
    // Nothing to apply doesn't mean nothing to do: `deep_link` for fixes that live
    // outside this tab, the owning section for the rest.
    const section = SECTION_BY_KIND[suggestion.kind]
    // Setup re-hosts the marketing settings components, so `open_settings` on a
    // suggestion we have a section for is a detour back into the same editor.
    const settlesInTab = suggestion.apply?.op === 'open_settings' && !!section
    const ctaLabel = suggestion.apply && !settlesInTab ? (CTA_LABEL[suggestion.apply.op] ?? 'Review change') : null
    const sectionCta = !ctaLabel && section && section !== currentSection ? section : null

    return (
        <div className="flex items-start gap-3 py-3 px-3 border-b last:border-b-0">
            <SuggestionIcon suggestion={suggestion} />

            <div className="grow min-w-0 deprecated-space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold">{suggestion.title}</span>
                    {suggestion.source === 'ai' && (
                        <Tooltip title="Suggested by AI from your data. Review the evidence before applying.">
                            <LemonTag type="completion" size="small">
                                AI
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>

                <div className="text-sm text-secondary">{suggestion.evidence}</div>

                {suggestion.unlocks.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap text-xs text-secondary">
                        <Tooltip title="The metrics this fix makes available. They stay empty or wrong until it's done.">
                            <span className="border-b border-dotted border-secondary cursor-help">Unlocks</span>
                        </Tooltip>
                        {suggestion.unlocks.map((capability) => (
                            <Tooltip key={capability} title={CAPABILITY_COPY[capability]?.what}>
                                <LemonTag size="small" type="muted">
                                    {CAPABILITY_COPY[capability]?.label ?? capability}
                                </LemonTag>
                            </Tooltip>
                        ))}
                    </div>
                )}

                {urlFix && <UrlFixHint fix={urlFix} />}
            </div>

            <div className="flex items-center gap-1 shrink-0">
                {ctaLabel && (
                    <LemonButton type="primary" size="small" loading={isApplying} onClick={() => onReview(suggestion)}>
                        {ctaLabel}
                    </LemonButton>
                )}
                {!ctaLabel && suggestion.deep_link && (
                    <LemonButton type="secondary" size="small" to={suggestion.deep_link} targetBlank>
                        Open source
                    </LemonButton>
                )}
                {!suggestion.deep_link && sectionCta && (
                    <LemonButton type="secondary" size="small" onClick={() => setSetupSection(sectionCta)}>
                        {SECTION_LABEL[sectionCta]}
                    </LemonButton>
                )}
                {isDismissed ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        tooltip="Put this back in the list"
                        onClick={() => restoreSuggestion(suggestion.id)}
                    >
                        Restore
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        tooltip="Hide this — it stays hidden across rescans until you restore it, and nothing is fixed"
                        onClick={() => dismissSuggestion(suggestion.id)}
                    >
                        Dismiss
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
