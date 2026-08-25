import { CONVERSATION_ID, chatResponseChunk } from './__mocks__/chatResponse.mocks'
import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta } from '@storybook/react'
import { HttpResponse } from 'msw'
import { useEffect } from 'react'
import { twMerge } from 'tailwind-merge'

import { mswDecorator } from '~/mocks/browser'

import conversationList from './__mocks__/conversationList.json'
import { MaxInstance, MaxInstanceProps } from './Max'

// Storybook can mount a story with two concurrent component instances that share the same
// (conversation-keyed) maxThreadLogic. A plain per-instance effect would then auto-send the
// first message twice, duplicating the human bubble in the thread. This guard is shared across
// instances so each conversation auto-sends exactly once; it's released on unmount so navigating
// back to the story re-triggers the send.
const autoSentConversationIds = new Set<string>()
export function useAutoSendOnce(conversationId: string, ready: boolean, send: () => void): void {
    useEffect(() => {
        if (!ready || autoSentConversationIds.has(conversationId)) {
            return
        }
        autoSentConversationIds.add(conversationId)
        const timer = setTimeout(send, 0)
        return () => {
            clearTimeout(timer)
            autoSentConversationIds.delete(conversationId)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ready])
}

// Shared meta (decorators + parameters) for the PostHog AI story files. Each story file spreads
// this into its own `meta` and sets a distinct `title` — Storybook errors on duplicate titles.
export const sharedMeta: Meta = {
    decorators: [
        mswDecorator({
            post: {
                // nosemgrep: no-environments-api-urls-frontend -- MSW mock must match maxThreadLogic's real request path; the conversations API lives on /api/environments/
                '/api/environments/:team_id/conversations/': () => new HttpResponse(chatResponseChunk),
            },
            get: {
                '/api/organizations/@current/': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        is_ai_data_processing_approved: true,
                    },
                ],
                // nosemgrep: no-environments-api-urls-frontend -- MSW mock must match maxThreadLogic's real request path; the conversations API lives on /api/environments/
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
                // nosemgrep: no-environments-api-urls-frontend -- MSW mock must match maxThreadLogic's real request path; the conversations API lives on /api/environments/
                [`/api/environments/:team_id/conversations/${CONVERSATION_ID}/`]: () => [
                    200,
                    {
                        id: CONVERSATION_ID,
                        status: 'idle',
                        title: 'Test Conversation',
                        created_at: '2025-04-29T17:44:21.654307Z',
                        updated_at: '2025-04-29T17:44:29.184791Z',
                        user: MOCK_DEFAULT_BASIC_USER,
                        messages: [],
                    },
                ],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
}

export const Template = ({
    className,
    ...props
}: Omit<MaxInstanceProps, 'tabId'> & { className?: string }): JSX.Element => {
    return (
        <div className={twMerge('relative flex flex-col h-fit', className)}>
            <MaxInstance tabId="storybook" {...props} />
        </div>
    )
}

export function generateChunk(events: string[]): string {
    return events.map((event) => (event.startsWith('event:') ? `${event}\n` : `${event}\n\n`)).join('')
}
