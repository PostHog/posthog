/**
 * `/approvals` — fleet-wide approval inbox.
 *
 * Lists every `agent_tool_approval_request` row across every agent in the
 * team. Drives the sidebar count badge via `pendingApprovalsCount` on the
 * fleet stats response.
 */

import { ApprovalsClient } from './approvals-client'

export default function ApprovalsPage(): React.ReactElement {
    return <ApprovalsClient />
}
