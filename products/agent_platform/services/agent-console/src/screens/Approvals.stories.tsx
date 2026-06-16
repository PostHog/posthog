/**
 * `<Approvals>` stories — the fleet-wide approval inbox.
 *
 * The screen is presentation-only (selection is normally driven by the
 * `?request=<id>` URL param); these stories wrap it in a tiny stateful
 * harness so clicking a row opens the detail pane, mirroring the route
 * client. The embedded `<ApprovalDetail>` fetches through `apiClient`, so
 * the harness sits inside `<SessionProvider>` + `<SessionGate>` and relies
 * on the MSW approval handlers in `.storybook/mocks/`.
 */

import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { agents, fleetApprovals, queuedPrApproval } from '@posthog/agent-chat/fixtures'

import { SessionGate, SessionProvider } from '@/components/session-context'

import { Approvals, type ApprovalsProps } from './Approvals'

type HarnessProps = Omit<ApprovalsProps, 'selectedId' | 'onSelect' | 'onReload'> & {
    initialSelectedId?: string | null
}

function ApprovalsHarness({ initialSelectedId = null, ...rest }: HarnessProps): React.ReactElement {
    const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId)
    return <Approvals {...rest} selectedId={selectedId} onSelect={setSelectedId} onReload={() => undefined} />
}

const meta: Meta<typeof ApprovalsHarness> = {
    title: 'Agent console components/Pages/Approvals',
    component: ApprovalsHarness,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <SessionProvider>
                <SessionGate>
                    <div className="h-screen w-full">
                        <Story />
                    </div>
                </SessionGate>
            </SessionProvider>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ApprovalsHarness>

export const Inbox: Story = {
    args: { approvals: fleetApprovals, agents, loading: false, error: null },
}

export const WithSelection: Story = {
    args: { approvals: fleetApprovals, agents, loading: false, error: null, initialSelectedId: queuedPrApproval.id },
}

export const Empty: Story = {
    args: { approvals: [], agents, loading: false, error: null },
}

export const AdminError: Story = {
    args: {
        approvals: [],
        agents,
        loading: false,
        error: "Approvals are admin-only — your account doesn't have admin scope on this project.",
    },
}
