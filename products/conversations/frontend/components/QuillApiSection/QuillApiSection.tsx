import { Button, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { WebAndApiAccessSummary } from '../WebAndApiAccessSummary/WebAndApiAccessSummary'

export function QuillApiSection(): JSX.Element {
    return (
        <QuillSettingsSubsection
            title="Direct API"
            description={
                <>
                    Build a custom support UI on top of the conversations API — send messages, fetch tickets, mark as
                    read, and restore conversations across browsers.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/support/javascript-api" target="_blank" />}
                    >
                        JavaScript API reference
                    </Button>
                </>
            }
        >
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        The API is available on <code>posthog.conversations</code> as soon as Support is enabled. No
                        additional setup is required.
                    </ItemDescription>
                </ItemContent>
            </Item>
            <WebAndApiAccessSummary />
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="medium" render={<p className="m-0" />}>
                    Quick example
                </Text>
                <pre data-quill className="m-0 overflow-x-auto rounded-md bg-muted p-3 text-xs">
                    {`if (posthog.conversations.isAvailable()) {
    const response = await posthog.conversations.sendMessage('Hello, I need help!', {
        name: 'John Doe',
        email: 'john@example.com',
    })
    console.log('Ticket created:', response.ticket_id)
}`}
                </pre>
            </div>
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="medium" render={<p className="m-0" />}>
                    Common methods
                </Text>
                <Text size="xs" variant="muted" render={<ul className="m-0 flex list-disc flex-col gap-0.5 pl-5" />}>
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
                </Text>
            </div>
        </QuillSettingsSubsection>
    )
}
