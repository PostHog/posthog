import {
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
} from '~/queries/schema/schema-assistant-messages'

import { MaxContextType } from '../maxTypes'
import failureMessage from './failureMessage.json'
import summaryMessage from './summaryMessage.json'
import visualizationMessage from './visualizationMessage.json'

// The session ID is hard-coded here, as it's used for randomizing the welcome headline
export const CONVERSATION_ID = 'b1b4b3b4-1b3b-4b3b-1b3b4b3b4b3b'

export const humanMessage: HumanMessage = {
    type: AssistantMessageType.Human,
    content: 'What are my most popular pages?',
    id: 'human-1',
}

const reasoningMessage1: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content: '',
    id: 'reasoning-1',
    meta: {
        thinking: [{ thinking: 'Picking relevant events and properties' }],
    },
}

const reasoningMessage2: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content: '',
    id: 'reasoning-2',
    meta: {
        thinking: [{ thinking: 'Generating trends' }],
    },
}

function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}

export const chatResponseChunk = generateChunk([
    'event: conversation',
    `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
    'event: message',
    `data: ${JSON.stringify(humanMessage)}`,
    'event: message',
    `data: ${JSON.stringify(reasoningMessage1)}`,
    'event: message',
    `data: ${JSON.stringify(reasoningMessage2)}`,
    'event: message',
    `data: ${JSON.stringify(visualizationMessage)}`,
    'event: message',
    `data: ${JSON.stringify(summaryMessage)}`,
])

export const chatMidwayResponseChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(reasoningMessage1)}`,
    'event: message',
    `data: ${JSON.stringify(reasoningMessage2)}`,
])

const generationFailure: FailureMessage = {
    type: AssistantMessageType.Failure,
    content: 'Oops! It looks like I’m having trouble answering this. Could you please try again?',
}

export const generationFailureChunk = generateChunk(['event: message', `data: ${JSON.stringify(generationFailure)}`])

export const failureChunk = generateChunk(['event: message', `data: ${JSON.stringify(failureMessage)}`])

const formMessage: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content: 'Does this look like a good summary of what your product does?',
    id: 'assistant-1',
    meta: {
        form: {
            options: [
                {
                    value: 'Yes, save this',
                    variant: 'primary',
                },
                {
                    value: 'No, not quite right',
                },
            ],
        },
    },
}

export const formChunk = generateChunk(['event: message', `data: ${JSON.stringify(formMessage)}`])

export const longMessage: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content: 'This\n\nis\n\na\n\nlong\n\nmessage\n\nthat\n\nshould\n\nbe\n\nsplit\n\ninto\n\nmultiple\n\nlines',
    id: 'assistant-2',
}

export const longResponseChunk = generateChunk([
    'event: message',
    `data: ${JSON.stringify(humanMessage)}`,
    'event: message',
    `data: ${JSON.stringify(longMessage)}`,
])

const humanMessageWithContext: HumanMessage = {
    type: AssistantMessageType.Human,
    content: 'Tell me about the $pageview event',
    id: 'human-context',
    ui_context: {
        events: [
            {
                id: 'test-event-1',
                name: '$pageview',
                type: MaxContextType.EVENT,
                description: 'Page view event',
            },
        ],
    },
}

const assistantResponseWithContext: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content:
        'Based on the event context you provided, the $pageview event is a standard event that tracks when users view pages in your application. This event helps you understand user navigation patterns and page popularity. It typically captures properties like the page URL, referrer, and timestamp.',
    id: 'assistant-context',
}

export const chatResponseWithEventContext = generateChunk([
    'event: conversation',
    `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
    'event: message',
    `data: ${JSON.stringify(humanMessageWithContext)}`,
    'event: message',
    `data: ${JSON.stringify(assistantResponseWithContext)}`,
])

const sqlMessage: AssistantMessage = {
    type: AssistantMessageType.Assistant,
    content: `Here's the SQL query you requested:\n\n\`\`\`sql\nSELECT users.id, users.email, users.name, orders.order_id, orders.total_amount, orders.order_date, products.product_name, products.category, order_items.quantity, order_items.price FROM users INNER JOIN orders ON users.id = orders.user_id INNER JOIN order_items ON orders.order_id = order_items.order_id INNER JOIN products ON order_items.product_id = products.id WHERE orders.order_date >= '2024-01-01' AND orders.status = 'completed' AND users.country = 'US' ORDER BY orders.total_amount DESC LIMIT 100\n\`\`\`\n\nThis query joins multiple tables to get comprehensive order information.`,
    id: 'sql-msg-1',
}

export const sqlQueryResponseChunk = generateChunk([
    'event: conversation',
    `data: ${JSON.stringify({ id: CONVERSATION_ID })}`,
    'event: message',
    `data: ${JSON.stringify({ ...humanMessage, content: 'Show me a complex SQL query' })}`,
    'event: message',
    `data: ${JSON.stringify(sqlMessage)}`,
])
