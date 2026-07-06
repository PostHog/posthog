import { dayjs } from 'lib/dayjs'

import { SignalReport, SignalReportStatus } from '../../types'
import { ReportCard } from '../cards/ReportCard'
import { playMeep } from './meep'

/**
 * Onboarding previews that render the *real* inbox `ReportCard` (the very component the Pull
 * requests / Reports tabs use), fed mock data – so they read as the genuine article rather than a
 * lookalike. Every click inside a card is intercepted (capture phase) so a sample never navigates
 * or archives; instead it nudges the user toward setup (with a cheeky `meep` sound), keeping the
 * samples inert while still feeling alive.
 *
 * The sample work is a wink at Silicon Valley (the show): Pied Piper's middle-out compression and
 * the ever-looming Hooli.
 */

// Timestamps are relative to "now" at render time (not a fixed calendar date) so `ReportCard`'s
// `TZLabel` always reads as just-landed work ("2 hours ago") instead of drifting to "months ago".
// Subtracting from the current clock also keeps the relative label stable in snapshot/VR runs.
const landedHoursAgo = (hours: number): string => dayjs().subtract(hours, 'hours').toISOString()

// A shippable fix Pied Piper's agents could open against the compression engine.
const PULL_REQUEST_SAMPLE: Omit<SignalReport, 'created_at' | 'updated_at'> = {
    id: 'onboarding-preview-pr',
    title: 'fix(compression): stop 4K streams dropping to single-threaded encode',
    summary:
        'Middle-out throughput fell 41% above 2160p after the Anton migration – the Weissman score slid from 5.2 to 2.9 and p95 encode time tripled. This repins the chunk scheduler and restores both to pre-migration numbers.',
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 3,
    relevant_user_count: null,
    artefact_count: 0,
    is_suggested_reviewer: false,
    priority: 'P1',
    source_products: ['session_replay'],
    implementation_pr_url: 'https://github.com/PiedPiper/pipernet/pull/486',
}

// A "needs your call" report: no clean code change, a judgment to make.
const REPORT_SAMPLE: Omit<SignalReport, 'created_at' | 'updated_at'> = {
    id: 'onboarding-preview-report',
    title: 'Hooli traffic is hammering the Pipernet beta – throttle or let it ride?',
    summary:
        "Sign-ups from Hooli IP ranges jumped 6× overnight and mostly bounce at onboarding. Could be Gavin's team load-testing us, or real interest worth keeping – worth your call before we rate-limit.",
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 5,
    relevant_user_count: null,
    artefact_count: 0,
    is_suggested_reviewer: false,
    priority: 'P2',
    actionability: 'requires_human_input',
    source_products: ['error_tracking', 'session_replay'],
}

/**
 * Wraps a real `ReportCard` so the whole card is inert-but-playful: an `onClickCapture` swallows
 * every click (stopping the card's links/buttons from navigating or archiving) and nudges the user
 * toward setup instead.
 */
function MeepCard({ report, tabKey }: { report: SignalReport; tabKey: 'pulls' | 'reports' }): JSX.Element {
    return (
        // `@container` so ReportCard's `@lg:` row layout resolves against the preview width (it has no
        // inbox-list container here). `role="presentation"` – the swallowed clicks are pure flair.
        <div
            role="presentation"
            className="@container"
            onClickCapture={(event) => {
                event.preventDefault()
                event.stopPropagation()
                playMeep()
            }}
        >
            <ReportCard report={report} tabKey={tabKey} />
        </div>
    )
}

export function PullRequestPreview(): JSX.Element {
    const landed = landedHoursAgo(2)
    return <MeepCard report={{ ...PULL_REQUEST_SAMPLE, created_at: landed, updated_at: landed }} tabKey="pulls" />
}

export function ReportPreview(): JSX.Element {
    const landed = landedHoursAgo(4)
    return <MeepCard report={{ ...REPORT_SAMPLE, created_at: landed, updated_at: landed }} tabKey="reports" />
}
