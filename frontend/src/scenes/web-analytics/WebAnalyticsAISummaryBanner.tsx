import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCopy, IconMagicWand } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { webAnalyticsAISummaryLogic } from './webAnalyticsAISummaryLogic'

export function WebAnalyticsAISummaryBanner(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { summary, summaryLoading, errorMessage, isExpanded } = useValues(webAnalyticsAISummaryLogic)
    const { generateSummary, setExpanded } = useActions(webAnalyticsAISummaryLogic)

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_AI_SUMMARY]) {
        return null
    }

    const hasContent = !!summary || summaryLoading || !!errorMessage

    return (
        <div
            className="border rounded bg-surface-primary mb-2 overflow-hidden"
            data-attr="web-analytics-ai-summary-banner"
        >
            <div className="flex items-center justify-between h-11 px-3">
                <div className="flex items-center gap-2 font-semibold">
                    <IconMagicWand className="text-primary" fontSize="18" />
                    <span>AI summary</span>
                    {summary && (
                        <span className="text-secondary text-xs font-normal">
                            Generated <TZLabel time={summary.created_at} />
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    {!hasContent && (
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconMagicWand />}
                            onClick={() => generateSummary()}
                            loading={summaryLoading}
                            data-attr="web-analytics-ai-summary-generate"
                        >
                            Generate AI summary
                        </LemonButton>
                    )}
                    {summary && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            tooltip="Copy summary to clipboard"
                            aria-label="Copy summary to clipboard"
                            onClick={() => {
                                void copyToClipboard(summary.summary_text, 'AI summary')
                            }}
                            data-attr="web-analytics-ai-summary-copy"
                        />
                    )}
                    {hasContent && (
                        <LemonButton
                            size="small"
                            icon={<IconChevronDown className={isExpanded ? '' : 'rotate-180'} />}
                            onClick={() => setExpanded(!isExpanded)}
                            tooltip={isExpanded ? 'Collapse' : 'Expand'}
                            aria-label={isExpanded ? 'Collapse summary' : 'Expand summary'}
                        />
                    )}
                </div>
            </div>
            {isExpanded && hasContent && (
                <div className="px-3 pb-3 border-t pt-2">
                    {summaryLoading ? (
                        <div className="flex items-center gap-2 text-sm text-secondary">
                            <Spinner /> Analyzing your data...
                        </div>
                    ) : errorMessage ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => generateSummary(),
                            }}
                        >
                            <div className="text-sm font-normal">
                                <strong>Summary failed.</strong> {errorMessage}
                            </div>
                        </LemonBanner>
                    ) : summary ? (
                        <LemonMarkdown lowKeyHeadings className="text-sm leading-relaxed">
                            {summary.summary_text}
                        </LemonMarkdown>
                    ) : null}
                </div>
            )}
        </div>
    )
}
