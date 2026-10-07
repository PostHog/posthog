import { LemonTabs } from '@posthog/lemon-ui'

import { TraceMode } from '../types'

export interface TraceModeTabsProps {
    mode: TraceMode
    onModeChange: (mode: TraceMode) => void
}

export function TraceModeTabs({ mode, onModeChange }: TraceModeTabsProps): JSX.Element {
    return (
        <LemonTabs<TraceMode>
            activeKey={mode}
            onChange={onModeChange}
            data-attr="trace-view-mode-tabs"
            tabs={[
                { key: 'spans', label: 'Spans', 'data-attr': 'trace-view-mode-spans' },
                { key: 'thread', label: 'Thread', 'data-attr': 'trace-view-mode-thread' },
                { key: 'timeline', label: 'Timeline', 'data-attr': 'trace-view-mode-timeline' },
            ]}
        />
    )
}
