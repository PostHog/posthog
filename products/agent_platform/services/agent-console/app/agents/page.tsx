/**
 * `/agents` — fleet list.
 *
 * Promoted out of `/` when the overview became the home — same client,
 * just under a dedicated path so the overview can host the embedded
 * concierge chat without the agents list crowding it.
 */

import { AgentsListClient } from '../agents-list-client'

export default function AgentsPage(): React.ReactElement {
    return <AgentsListClient />
}
