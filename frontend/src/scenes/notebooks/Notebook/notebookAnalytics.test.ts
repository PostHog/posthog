import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'

import { AccessControlLevel, UserType } from '~/types'

import { NotebookType } from '../types'
import type { InlineAICompletion } from './MarkdownNotebookInlineAI'
import {
    NotebookInlineAIFinishedProperties,
    NotebookOpenedProperties,
    buildNotebookInlineAIFinishedEvent,
    buildNotebookInlineAIRequestedEvent,
    buildNotebookOpenedEvent,
} from './notebookAnalytics'

describe('notebookAnalytics', () => {
    describe('buildNotebookOpenedEvent', () => {
        const user = { uuid: 'user-1' } as UserType

        const notebook = (overrides: Partial<NotebookType> = {}): NotebookType =>
            ({
                short_id: 'abc123',
                created_by: { uuid: 'user-1' },
                user_access_level: AccessControlLevel.Editor,
                content: { type: 'doc', content: [{}, {}, {}] },
                ...overrides,
            }) as NotebookType

        it.each([
            [
                'the creator opening directly (counts top-level nodes)',
                {},
                false,
                {
                    short_id: 'abc123',
                    is_creator: true,
                    user_access_level: AccessControlLevel.Editor,
                    access_source: 'direct',
                    node_count: 3,
                },
            ],
            [
                'a viewer of another user’s notebook via shared link',
                { created_by: { uuid: 'other' } as UserType },
                true,
                { is_creator: false, access_source: 'shared_link' },
            ],
            [
                'a notebook with no content and no creator',
                { content: null, created_by: null },
                false,
                { is_creator: false, node_count: 0 },
            ],
        ] as [string, Partial<NotebookType>, boolean, Partial<NotebookOpenedProperties>][])(
            'builds the event for %s',
            (_label, overrides, isShared, expected) => {
                expect(buildNotebookOpenedEvent(notebook(overrides), user, isShared)).toMatchObject(expected)
            }
        )

        it.each([
            ['scratchpad', 'scratchpad'],
            ['template', 'template-onboarding'],
            ['no notebook loaded', undefined],
        ])('does not emit for %s', (_label, shortId) => {
            const nb = shortId === undefined ? null : notebook({ short_id: shortId })
            expect(buildNotebookOpenedEvent(nb, user, false)).toBeNull()
        })
    })

    describe('inline AI events', () => {
        const request = (overrides: Partial<MarkdownNotebookAskAIRequest> = {}): MarkdownNotebookAskAIRequest => ({
            conversationId: 'conversation-1',
            query: 'Summarize signups',
            source: 'slash',
            responseNodeId: 'node-1',
            responseNodeIndex: 2,
            responseMarker: 'Thinking...',
            markdown: '# Private notebook text',
            markdownWithResponse: '# Private notebook text\n\nThinking...',
            ...overrides,
        })

        it.each([
            ['a slash command', {}, { source: 'slash', has_selection: false }],
            [
                'a selection',
                { source: 'selection', selectedMarkdown: 'Private selected text', selectedRefId: 'ref-1' },
                { source: 'selection', has_selection: true },
            ],
        ] as [
            string,
            Partial<MarkdownNotebookAskAIRequest>,
            Partial<ReturnType<typeof buildNotebookInlineAIRequestedEvent>>,
        ][])('builds the requested event for %s without prompt or notebook text', (_label, overrides, expected) => {
            expect(buildNotebookInlineAIRequestedEvent(request(overrides), 'abc123')).toEqual({
                conversation_id: 'conversation-1',
                notebook_short_id: 'abc123',
                prompt_length: 'Summarize signups'.length,
                ...expected,
            })
        })

        it.each([
            [
                'an artifact that updated the notebook',
                { status: 'done', kind: 'artifact', hasArtifact: true, message: 'Updated the notebook.' },
                1000,
                { status: 'done', result_kind: 'artifact', has_artifact: true, duration_ms: 1500 },
            ],
            [
                'a failed request',
                { status: 'error', kind: 'error', hasArtifact: false, message: 'Private error text' },
                1000,
                { status: 'error', result_kind: 'error', has_artifact: false, duration_ms: 1500 },
            ],
            [
                'a request whose start time was lost',
                { status: 'done', kind: 'assistant', hasArtifact: false, message: 'Private answer' },
                undefined,
                { status: 'done', result_kind: 'assistant', duration_ms: null },
            ],
        ] as [string, InlineAICompletion, number | undefined, Partial<NotebookInlineAIFinishedProperties>][])(
            'builds the finished event for %s',
            (_label, completion, startedAtMs, expected) => {
                const event = buildNotebookInlineAIFinishedEvent(request(), completion, 'abc123', startedAtMs, 2500)

                expect(event).toMatchObject({ conversation_id: 'conversation-1', ...expected })
                expect(JSON.stringify(event)).not.toContain('Private')
            }
        )
    })
})
