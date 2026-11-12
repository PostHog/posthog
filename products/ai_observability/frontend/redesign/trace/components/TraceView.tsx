import { ReactNode } from 'react'

import { LabeledLink, LoadFailure } from '../types'
import { TraceViewError } from './TraceViewError'
import { TraceViewLoading } from './TraceViewLoading'

export type TraceViewProps =
    | { status: 'loading' }
    | { status: 'error'; loadFailure: LoadFailure; backLink: LabeledLink | null }
    | { status: 'ready'; header: ReactNode; summaryBar: ReactNode; modeTabs: ReactNode; body: ReactNode }

export function TraceView(props: TraceViewProps): JSX.Element {
    if (props.status === 'loading') {
        return <TraceViewLoading />
    }
    if (props.status === 'error') {
        return <TraceViewError loadFailure={props.loadFailure} backLink={props.backLink} />
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-4">
            {props.header}
            {props.summaryBar}
            {props.modeTabs}
            <div className="min-h-0 flex-1 overflow-y-auto">{props.body}</div>
        </div>
    )
}
