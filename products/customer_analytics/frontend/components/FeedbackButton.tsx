import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillFeedbackButton } from './QuillFeedbackButton'

export function FeedbackButton({ id }: { id: string }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return <QuillFeedbackButton id={id} />
    }
    return (
        <LemonButton size="small" id={id} tooltip="Have any questions or feedback?">
            Feedback
        </LemonButton>
    )
}
