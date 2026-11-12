import { useMountedLogic, useValues } from 'kea'
import { memo, useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { saveToDatasetButtonLogic } from '../../datasets/saveToDatasetButtonLogic'
import { TraceView } from './components/TraceView'
import { TraceFeedbackHost } from './hosts/TraceFeedbackHost'
import { TraceHeaderHost } from './hosts/TraceHeaderHost'
import { TraceModeTabsHost } from './hosts/TraceModeTabsHost'
import { TraceSpansHost } from './hosts/TraceSpansHost'
import { TraceSummaryBarHost } from './hosts/TraceSummaryBarHost'
import { TraceSummaryModeHost } from './hosts/TraceSummaryModeHost'
import { TraceThreadHost } from './hosts/TraceThreadHost'
import { TraceTimelineHost } from './hosts/TraceTimelineHost'
import { traceReviewLogic } from './traceReviewLogic'
import { traceViewHostLogic } from './traceViewHostLogic'
import { traceViewLogic } from './traceViewLogic'
import { traceViewModelLogic } from './traceViewModelLogic'
import { LabeledLink, TraceMode, TraceViewKey } from './types'

export interface TraceViewHostProps extends TraceViewKey {
    backLink: LabeledLink | null
}

const BODY_HOSTS: Record<TraceMode, (props: TraceViewKey) => JSX.Element | null> = {
    spans: TraceSpansHost,
    thread: TraceThreadHost,
    summary: TraceSummaryModeHost,
    feedback: TraceFeedbackHost,
    timeline: TraceTimelineHost,
}

export const TraceViewHost = memo(function TraceViewHost({
    hostId,
    traceId,
    timestampHint,
    backLink,
}: TraceViewHostProps): JSX.Element {
    const key = { hostId, traceId, timestampHint }
    const { status, loadFailure } = useValues(traceViewLogic({ traceId, timestampHint }))
    const { mode } = useValues(traceViewHostLogic({ hostId }))
    const { featureFlags } = useValues(featureFlagLogic)
    // Mounted before the trace arrives: it reads a step the URL names, opens Summary from a link and seeds the search,
    // and through it the feedback and search logics catch the trace load they wait for.
    useMountedLogic(traceViewModelLogic(key))
    // The review status read runs alongside the trace read rather than after it.
    useMountedLogic(traceReviewLogic({ traceId }))
    const datasetsEnabled = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]
    // The dataset button remounts on every step and mode change. Its logic has no key, so it would refetch datasets and
    // recents on every remount without this mount.
    useEffect(() => (datasetsEnabled ? saveToDatasetButtonLogic.mount() : undefined), [datasetsEnabled])

    if (status === 'error' && loadFailure) {
        return <TraceView status="error" loadFailure={loadFailure} backLink={backLink} />
    }
    if (status !== 'ready') {
        return <TraceView status="loading" />
    }
    const Body = BODY_HOSTS[mode]
    return (
        <TraceView
            status="ready"
            header={<TraceHeaderHost {...key} backLink={backLink} />}
            summaryBar={<TraceSummaryBarHost {...key} />}
            modeTabs={<TraceModeTabsHost {...key} />}
            body={<Body {...key} />}
        />
    )
})
