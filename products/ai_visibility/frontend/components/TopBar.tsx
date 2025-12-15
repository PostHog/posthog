import { IconLogomark, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { FeedbackButton } from './FeedbackButton'

export function TopBar({
    lastUpdated,
    onRefresh,
    isRefreshing,
}: {
    lastUpdated: string | null
    onRefresh: () => void
    isRefreshing: boolean
}): JSX.Element {
    const formattedDate = lastUpdated ? dayjs(lastUpdated).format('MMM D') : null

    return (
        <div className="flex items-center justify-between px-4 py-2 border-b bg-bg-light">
            <div className="flex items-center gap-2">
                <IconLogomark className="text-2xl" />
                <span className="font-semibold text-base">AI visibility</span>
            </div>
            <div className="flex items-center gap-3">
                {formattedDate && <span className="text-muted text-sm">Data last updated on {formattedDate}</span>}
                <FeedbackButton />
                <Tooltip title="Re-run analysis for this brand with fresh data (useful if you've updated your prompts)  ">
                    <LemonButton
                        size="small"
                        icon={<IconRefresh />}
                        type="secondary"
                        onClick={onRefresh}
                        loading={isRefreshing}
                    >
                        Re-run analysis
                    </LemonButton>
                </Tooltip>
                <LemonButton
                    size="small"
                    icon={<IconPlus />}
                    type="primary"
                    to="https://posthog-git-array-good-cinnamon-armadillo-post-hog.vercel.app/ai/visibility"
                    targetBlank
                >
                    New report
                </LemonButton>
            </div>
        </div>
    )
}
