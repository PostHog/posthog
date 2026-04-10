import { LemonCard, Link } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { SecretApiKeySection } from './SecretApiKeySection'
export function WorkflowsSection(): JSX.Element {
    return (
        <SceneSection
            title="Workflows"
            description={
                <>
                    Use these events as triggers in <Link to="/workflows">Workflows</Link> to automate ticket actions.{' '}
                    <Link to="https://posthog.com/docs/support/workflows" target="_blank">
                        Docs
                    </Link>
                </>
            }
        >
            <LemonCard hoverEffect={false} className="max-w-[800px] px-4 py-3">
                <div className="flex flex-col gap-4">
                    <div>
                        <h4 className="font-semibold mb-1">Trigger events</h4>
                        <p className="text-xs text-muted-alt mb-2">
                            These events are automatically captured when ticket or message state changes. Use them as
                            workflow triggers.
                        </p>
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b">
                                    <th className="text-left py-1.5 pr-4 font-medium">Event</th>
                                    <th className="text-left py-1.5 font-medium">When</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr className="border-b">
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_ticket_created</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">A customer opens a new ticket</td>
                                </tr>
                                <tr className="border-b">
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_ticket_status_changed</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">
                                        Ticket status changes (e.g. new → pending → resolved)
                                    </td>
                                </tr>
                                <tr className="border-b">
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_ticket_priority_changed</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">Ticket priority is set or changed</td>
                                </tr>
                                <tr className="border-b">
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_ticket_assigned</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">
                                        Ticket is assigned to a team member
                                    </td>
                                </tr>
                                <tr className="border-b">
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_message_sent</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">
                                        A team member sends a reply on a ticket
                                    </td>
                                </tr>
                                <tr>
                                    <td className="py-1.5 pr-4">
                                        <code className="text-xs">$conversation_message_received</code>
                                    </td>
                                    <td className="py-1.5 text-xs text-muted-alt">
                                        A customer sends a message on a ticket
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div>
                        <h4 className="font-semibold mb-1">Workflow actions</h4>
                        <p className="text-xs text-muted-alt">
                            Use <strong>Get ticket</strong> to fetch current ticket data into workflow variables
                            (ticket_status, ticket_priority, ticket_number, etc.) and <strong>Update ticket</strong> to
                            change a ticket's status or priority.
                        </p>
                    </div>
                </div>
            </LemonCard>
            <SecretApiKeySection />
        </SceneSection>
    )
}
