import { IconPullRequest, IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TodayFeedReportFacts } from './todayFeedReport'
import { pullRequestFact } from './todayRowFacts'

export function TodayFeedReportChips({
    pullRequest,
    prompt,
    onAsk,
}: Pick<TodayFeedReportFacts, 'pullRequest' | 'prompt'> & { onAsk: (prompt: string) => void }): JSX.Element {
    return (
        <>
            {pullRequest && (
                <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                    data-attr="today-feed-report-pr"
                >
                    <IconPullRequest />
                    {pullRequestFact(pullRequest.state)}
                    {pullRequest.number && <span translate="no">#{pullRequest.number}</span>}
                </Button>
            )}
            {prompt && (
                <Button
                    variant="outline"
                    size="sm"
                    className="min-w-0"
                    onClick={() => onAsk(prompt)}
                    data-attr="today-feed-report-ask"
                >
                    <IconSparkles />
                    <span className="truncate">{prompt}</span>
                </Button>
            )}
        </>
    )
}
