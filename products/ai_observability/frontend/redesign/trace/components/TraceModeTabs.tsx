import { LemonTabs } from '@posthog/lemon-ui'

import { TraceMode } from '../types'

export interface TraceModeTabsProps {
    mode: TraceMode
    onModeChange: (mode: TraceMode) => void
    /** Null until the feedback has loaded. */
    feedbackCount?: number | null
}

export function TraceModeTabs({ mode, onModeChange, feedbackCount = null }: TraceModeTabsProps): JSX.Element {
    return (
        <LemonTabs<TraceMode>
            activeKey={mode}
            onChange={onModeChange}
            data-attr="trace-view-mode-tabs"
            tabs={[
                { key: 'spans', label: 'Spans', 'data-attr': 'trace-view-mode-spans' },
                { key: 'thread', label: 'Thread', 'data-attr': 'trace-view-mode-thread' },
                { key: 'timeline', label: 'Timeline', 'data-attr': 'trace-view-mode-timeline' },
                { key: 'summary', label: 'Summary', 'data-attr': 'trace-view-mode-summary' },
                {
                    key: 'feedback',
                    label: feedbackCount ? `Feedback ${feedbackCount}` : 'Feedback',
                    'data-attr': 'trace-view-mode-feedback',
                },
            ]}
        />
    )
}
