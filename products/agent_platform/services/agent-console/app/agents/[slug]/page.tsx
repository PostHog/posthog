/**
 * `/agents/[slug]` — index segment. The agent's overview tab.
 *
 * The shared chrome (breadcrumb, header, tab strip) lives in
 * `[slug]/layout.tsx`. This segment only renders the overview body.
 */

import { OverviewSegment } from './overview-client'

export default function AgentDetailPage(): React.ReactElement {
    return <OverviewSegment />
}
