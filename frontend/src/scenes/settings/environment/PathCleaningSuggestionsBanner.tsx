import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { pathCleaningSuggestionsLogic } from './pathCleaningSuggestionsLogic'

function PathCleaningPreviewModal({
    suggestionId,
    restrictedReason,
}: {
    suggestionId: string
    restrictedReason: string | null
}): JSX.Element {
    const { previewOpen, preview, previewLoading } = useValues(pathCleaningSuggestionsLogic)
    const { closePreview, applySuggestion } = useActions(pathCleaningSuggestionsLogic)

    return (
        <LemonModal
            isOpen={previewOpen}
            onClose={closePreview}
            title="Preview on your real paths"
            description="Your most-viewed paths from the last 30 days, with all suggested rules applied in order. Nothing changes until you apply."
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closePreview}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => applySuggestion(suggestionId)}
                        disabledReason={restrictedReason}
                    >
                        Apply all
                    </LemonButton>
                </>
            }
        >
            {previewLoading || !preview ? (
                <div className="flex items-center justify-center py-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    <span className="text-secondary">
                        These rules group <strong>{preview.changed_path_count}</strong> of your top{' '}
                        <strong>{preview.sampled_path_count}</strong> paths
                        {preview.changed_path_count > preview.examples.length
                            ? ` — showing the first ${preview.examples.length}`
                            : ''}
                        .
                    </span>
                    <div className="flex flex-col gap-1 max-h-[30rem] overflow-y-auto">
                        {preview.examples.map((example) => (
                            <div
                                key={example.before}
                                className="flex flex-wrap items-center gap-2 font-mono text-xs border rounded p-2"
                            >
                                <code>{example.before}</code>
                                <IconArrowRight />
                                <code className="font-semibold">{example.after}</code>
                                <span className="text-secondary ml-auto font-sans">
                                    {humanFriendlyLargeNumber(example.views)} views
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </LemonModal>
    )
}

export function PathCleaningSuggestionsBanner(): JSX.Element | null {
    const flagEnabled = useFeatureFlag('WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS')
    const { latestSuggestion, suggestionsLoading } = useValues(pathCleaningSuggestionsLogic)
    const { applySuggestion, dismissSuggestion, openPreview } = useActions(pathCleaningSuggestionsLogic)
    // Applying writes path_cleaning_filters, an admin-gated team field — mirror the backend gate.
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!flagEnabled || suggestionsLoading || !latestSuggestion || latestSuggestion.rules.length === 0) {
        return null
    }

    const ruleCount = latestSuggestion.rules.length

    return (
        <>
            <LemonBanner
                type="info"
                className="mb-4"
                action={{
                    children: 'Apply all',
                    onClick: () => applySuggestion(latestSuggestion.id),
                    disabledReason: restrictedReason,
                }}
                onClose={() => dismissSuggestion(latestSuggestion.id)}
            >
                <div className="flex flex-col gap-2">
                    <span>
                        We analyzed your traffic and suggest <strong>{ruleCount}</strong> path cleaning{' '}
                        {ruleCount === 1 ? 'rule' : 'rules'} to group similar pages. Review and apply them:
                    </span>
                    <div className="flex flex-col gap-1">
                        {latestSuggestion.rules.map((rule) => (
                            <div key={rule.order} className="flex flex-wrap items-center gap-2 font-mono text-xs">
                                <code>{rule.regex}</code>
                                <IconArrowRight />
                                <code>{rule.alias}</code>
                                <span className="text-secondary">
                                    groups {rule.match_count} of your top {latestSuggestion.sampled_path_count} paths
                                </span>
                            </div>
                        ))}
                    </div>
                    <div>
                        <LemonButton type="secondary" size="xsmall" onClick={() => openPreview(latestSuggestion.id)}>
                            Preview on your paths
                        </LemonButton>
                    </div>
                </div>
            </LemonBanner>
            <PathCleaningPreviewModal suggestionId={latestSuggestion.id} restrictedReason={restrictedReason} />
        </>
    )
}
