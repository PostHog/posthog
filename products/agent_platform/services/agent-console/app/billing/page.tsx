/**
 * `/billing` — team-scoped Wallet + Ledger surface.
 *
 * Reads from the ai-gateway billing service via the Django proxy
 * (/api/projects/<team_id>/ai_gateway/...).
 */

import { BillingClient } from './billing-client'

export default function BillingPage(): React.ReactElement {
    return <BillingClient />
}
