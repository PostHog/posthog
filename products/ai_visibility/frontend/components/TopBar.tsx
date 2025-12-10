import { IconLogomark, IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    type="primary"
                    onClick={onRefresh}
                    loading={isRefreshing}
                >
                    Generate new report
                </LemonButton>
            </div>
        </div>
    )
}
