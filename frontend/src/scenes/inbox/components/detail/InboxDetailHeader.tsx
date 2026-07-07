import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { InboxTabKey, INBOX_TAB_LABEL, SignalReport } from '../../types'
import { displayConventionalCommitTitle, parseConventionalCommitTitle } from '../../utils/reportPresentation'
import { ConventionalCommitScopeTag } from '../cards/ReportCard'

/**
 * Header for the Runs detail view: a labeled back button, the conventional-commit title, and a
 * copy-link button that copies an absolute deep-link to the run. Report / PR / Not actionable
 * details render their own merged header inside `InboxDetailFrame`.
 */
export function InboxDetailHeader({ report, tab }: { report: SignalReport; tab: InboxTabKey }): JSX.Element {
    const conventionalTitle = parseConventionalCommitTitle(report.title)
    const displayTitle = displayConventionalCommitTitle(report.title, 'Untitled report')
    const reportPath = urls.inboxReport(tab, report.id)

    return (
        <div className="shrink-0 border-b border-primary px-6 pt-5 pb-4 flex flex-col gap-3">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconArrowLeft />}
                to={urls.inbox(tab)}
                className="-ml-2 w-fit"
            >
                {INBOX_TAB_LABEL[tab]}
            </LemonButton>
            <div className="flex items-start justify-between gap-3 min-w-0">
                <h1 className="min-w-0 flex-1 m-0 break-words text-2xl font-bold leading-tight tracking-tight">
                    {conventionalTitle && (
                        <ConventionalCommitScopeTag type={conventionalTitle.type} scope={conventionalTitle.scope} />
                    )}
                    {displayTitle}
                </h1>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconLink />}
                    tooltip="Copy a link to this report"
                    className="shrink-0"
                    onClick={() =>
                        void copyToClipboard(
                            `${window.location.origin}${addProjectIdIfMissing(reportPath)}`,
                            'report link'
                        )
                    }
                >
                    Copy link
                </LemonButton>
            </div>
        </div>
    )
}
