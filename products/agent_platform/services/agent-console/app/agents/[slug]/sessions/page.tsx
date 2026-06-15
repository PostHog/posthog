/**
 * `/agents/[slug]/sessions` — session list with optional master-detail.
 *
 * `?session=<id>` opens the selected session on the right pane. Listed
 * sessions tolerate janitor unavailability — empty list rather than
 * failing the segment.
 */

import { SessionsSegment } from './sessions-client'

export default function SessionsPage(): React.ReactElement {
    return <SessionsSegment />
}
