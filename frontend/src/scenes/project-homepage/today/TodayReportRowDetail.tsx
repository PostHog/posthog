import type { MouseEvent, ReactNode } from 'react'

import { IconArrowRight, IconArrowUpRight, IconPullRequest } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TodayReportPreview } from './todayReportPreviews'
import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

const PULL_REQUEST_STATES: Record<string, string> = {
    open: 'ready for review',
    draft: 'draft',
    merged: 'merged',
    closed: 'closed',
}

function PullRequestLink({
    pullRequest,
}: {
    pullRequest: NonNullable<TodayReportPreview['pullRequest']>
}): JSX.Element {
    const number = pullRequest.url.match(/\/pull\/(\d+)/)?.[1]
    const state = PULL_REQUEST_STATES[pullRequest.state ?? '']
    return (
        <LinkPrimitive
            to={pullRequest.url}
            target="_blank"
            className="TodayRow__detailPr"
            data-attr="today-list-report-pr"
        >
            <IconPullRequest className="size-3.5" aria-hidden />
            <span>{[number ? `Pull request #${number}` : 'Pull request', state].filter(Boolean).join(', ')}</span>
            <IconArrowUpRight className="size-3" aria-hidden />
        </LinkPrimitive>
    )
}

export function TodayReportRowDetail({
    preview,
    to,
    onOpen,
    actions,
    dataAttr,
}: {
    preview: TodayReportPreview
    to: string
    onOpen: () => void
    actions?: ReactNode
    dataAttr: string
}): JSX.Element {
    const openReport = (event: MouseEvent<HTMLElement>): void => {
        onOpen()
        if (isPlainClick(event)) {
            event.preventDefault()
            navigateWithCrossfade(to)
        }
    }
    const facts = [preview.sources, preview.metric && `${preview.metric.title}: ${preview.metric.value}`].filter(
        (fact): fact is string => !!fact
    )
    return (
        <div className="TodayRow__detailBody">
            {preview.lead && <p className="TodayRow__detailLead">{preview.lead}</p>}
            <div className="TodayRow__detailFooter">
                <p className="TodayRow__detailFacts">
                    <span>{facts.join(' · ')}</span>
                    {preview.pullRequest && (
                        <>
                            {facts.length > 0 && ' · '}
                            <PullRequestLink pullRequest={preview.pullRequest} />
                        </>
                    )}
                </p>
                <div className="TodayRow__detailActions">
                    {actions}
                    <Button
                        variant="outline"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={to} />}
                        onClick={openReport}
                        data-attr={dataAttr}
                    >
                        Open report
                        <IconArrowRight />
                    </Button>
                </div>
            </div>
        </div>
    )
}
