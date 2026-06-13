import { LemonBanner, LemonCard, Link } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

export function ApiSection(): JSX.Element {
    return (
        <SceneSection
            title="Direct API"
            description={
                <>
                    Build a custom support UI on top of the conversations API — send messages, fetch tickets, mark as
                    read, and restore conversations across browsers.{' '}
                    <Link to="https://posthog.com/docs/support/javascript-api" target="_blank" targetBlankIcon>
                        JavaScript API reference
                    </Link>
                </>
            }
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-3 max-w-[800px] px-4 py-3">
                <LemonBanner type="info">
                    The API is available on <code>posthog.conversations</code> as soon as Support is enabled — no
                    additional setup required. Configure <strong>Allowed domains</strong> and{' '}
                    <strong>Identity verification</strong> under the General tab.
                </LemonBanner>
                <div>
                    <p className="mb-2 font-medium">Quick example</p>
                    <pre className="bg-surface-secondary rounded p-3 text-xs overflow-x-auto mb-0">
                        {`if (posthog.conversations.isAvailable()) {
    const response = await posthog.conversations.sendMessage('Hello, I need help!', {
        name: 'John Doe',
        email: 'john@example.com',
    })
    console.log('Ticket created:', response.ticket_id)
}`}
                    </pre>
                </div>
                <div>
                    <p className="mb-1 font-medium">Common methods</p>
                    <ul className="text-xs text-muted-alt mb-0 pl-5 list-disc flex flex-col gap-0.5">
                        <li>
                            <code>sendMessage(message, userTraits?, newTicket?)</code> — send a customer message
                        </li>
                        <li>
                            <code>getMessages(ticketId?, after?)</code> — fetch messages for a ticket
                        </li>
                        <li>
                            <code>getTickets(options?)</code> — list tickets with optional status / pagination filters
                        </li>
                        <li>
                            <code>markAsRead(ticketId?)</code> — clear unread count for the customer
                        </li>
                        <li>
                            <code>requestRestoreLink(email)</code> — email a recovery link to restore tickets across
                            browsers
                        </li>
                    </ul>
                </div>
            </LemonCard>
        </SceneSection>
    )
}
