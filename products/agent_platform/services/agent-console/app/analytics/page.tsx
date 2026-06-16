/**
 * `/analytics` — fleet-wide AI observability dashboard.
 *
 * Rolls up every agent's `$ai_*` events (captured into this team's own project
 * by the runner) into cross-agent KPIs, spend/cost charts, and per-agent +
 * tool-reliability tables. Links out to the full AI observability product for
 * trace-level depth.
 */

import { AnalyticsClient } from './analytics-client'

export default function AnalyticsPage(): React.ReactElement {
    return <AnalyticsClient />
}
