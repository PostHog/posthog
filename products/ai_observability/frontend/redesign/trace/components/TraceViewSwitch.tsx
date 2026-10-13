import { Link } from '@posthog/lemon-ui'

import { TraceViewChoice } from '../types'

export interface TraceViewSwitchProps {
    view: TraceViewChoice
    onSwitch: (view: TraceViewChoice) => void
}

export function TraceViewSwitch({ view, onSwitch }: TraceViewSwitchProps): JSX.Element {
    const isNewView = view === 'new'
    return (
        <div
            className="flex flex-wrap items-center justify-end gap-x-2 text-xs text-secondary"
            data-attr="trace-view-switch"
        >
            <span>{isNewView ? "You're on the new trace view." : "There's a new trace view."}</span>
            <Link
                onClick={() => onSwitch(isNewView ? 'legacy' : 'new')}
                data-attr={isNewView ? 'trace-view-switch-to-legacy' : 'trace-view-switch-to-new'}
            >
                {isNewView ? 'Switch to the old view' : 'Switch to the new view'}
            </Link>
        </div>
    )
}
