import clsx from 'clsx'

import { IconSparkles } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { QueryScanState, fixableQueryScanFindings, queryScanStatLine } from './queryScan'
import { QueryScanFindingList } from './QueryScanFindingList'

export interface QueryScanBannerProps {
    queryScan: QueryScanState | null
    /** Opens the assistant on the findings. Left out where there is no editor to write into. */
    onFixWithAI?: () => void
    className?: string
}

export function QueryScanBanner({ queryScan, onFixWithAI, className }: QueryScanBannerProps): JSX.Element | null {
    if (!queryScan) {
        return null
    }

    const { summary, findings } = queryScan
    const showFindings = summary.status === 'done' && findings.length > 0
    const fixableFindings = fixableQueryScanFindings(findings)

    return (
        <div className={clsx('flex flex-col gap-2 shrink-0', className)} data-attr="query-scan">
            <span className="text-xs text-secondary">{queryScanStatLine(summary)}</span>
            {showFindings && (
                <LemonBanner type="warning">
                    <QueryScanFindingList findings={findings} />
                    {onFixWithAI && fixableFindings.length > 0 && (
                        <LemonButton
                            className="mt-2"
                            type="secondary"
                            size="small"
                            icon={<IconSparkles />}
                            onClick={onFixWithAI}
                            data-attr="query-scan-fix-with-ai"
                        >
                            Fix with AI
                        </LemonButton>
                    )}
                </LemonBanner>
            )}
        </div>
    )
}
