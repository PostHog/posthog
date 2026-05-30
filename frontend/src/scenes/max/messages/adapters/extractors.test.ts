import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { McpToolCallMessage } from '../../maxTypes'
import {
    extractContentText,
    extractRecordingFilters,
    extractSummarizePayload,
    extractVisualizationArtifact,
} from './extractors'

function makeMessage(overrides: Partial<McpToolCallMessage>): McpToolCallMessage {
    return {
        type: 'mcp_tool_call',
        id: 'msg-1',
        toolCallId: 'tc-1',
        resolvedKey: 'query-session-recordings-list',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        status: 'completed',
        ...overrides,
    }
}

describe('max/messages/adapters/extractors', () => {
    describe('extractRecordingFilters()', () => {
        it('builds a defined filter_group and duration from a flat AssistantRecordingsQuery input', () => {
            const message = makeMessage({
                innerInput: {
                    kind: NodeKind.RecordingsQuery,
                    date_from: '-7d',
                    filter_test_accounts: true,
                    properties: [
                        {
                            type: PropertyFilterType.Person,
                            key: 'email',
                            value: 'a@b.com',
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
                rawOutput: { results: [] },
            })

            const filters = extractRecordingFilters(message)

            // Would have thrown in sessionRecordingsPlaylistLogic without these two fields.
            expect(filters).not.toBeNull()
            expect(filters?.filter_group).not.toBeUndefined()
            expect(filters?.filter_group.type).not.toBeUndefined()
            expect(Array.isArray(filters?.filter_group.values)).toBe(true)
            expect(Array.isArray(filters?.duration)).toBe(true)
            expect(filters?.duration.length).toBeGreaterThan(0)

            // The flat scalars carry over.
            expect(filters?.date_from).toBe('-7d')
            expect(filters?.filter_test_accounts).toBe(true)

            // The input property is folded into the nested group's values bucket.
            const nested = filters?.filter_group.values.find(
                (group): group is { type: any; values: any[] } =>
                    typeof group === 'object' && group !== null && 'values' in group
            )
            expect(nested?.values).toHaveLength(1)
            expect(nested?.values[0]).toMatchObject({ key: 'email' })
        })

        it('seeds an empty but defined filter_group when no properties are present', () => {
            const filters = extractRecordingFilters(
                makeMessage({ innerInput: { kind: NodeKind.RecordingsQuery, date_to: '2024-01-01' } })
            )

            expect(filters?.filter_group).not.toBeUndefined()
            expect(Array.isArray(filters?.filter_group.values)).toBe(true)
            expect(filters?.duration.length).toBeGreaterThan(0)
            expect(filters?.date_from).toBeNull()
            expect(filters?.date_to).toBe('2024-01-01')
        })

        it('honors an already-built filter_group on the input verbatim', () => {
            const prebuiltGroup = {
                type: 'OR',
                values: [{ type: 'person', key: 'email', value: 'x', operator: 'exact' }],
            }
            const filters = extractRecordingFilters(
                makeMessage({ innerInput: { filter_group: prebuiltGroup, date_from: '-1d' } })
            )

            expect(filters?.filter_group).toEqual(prebuiltGroup)
            expect(filters?.duration.length).toBeGreaterThan(0)
            expect(filters?.date_from).toBe('-1d')
        })

        it('returns null when there is no input or output filters payload', () => {
            expect(extractRecordingFilters(makeMessage({ innerInput: {}, rawInput: {} }))).toBeNull()
        })
    })

    describe('extractContentText()', () => {
        it('joins text frames and drops non-text frames', () => {
            const text = extractContentText([
                { type: 'text', text: 'first' },
                { type: 'image', data: 'x' },
                { type: 'text', text: 'second' },
            ])
            expect(text).toBe('first\nsecond')
        })

        it('returns empty string for undefined content', () => {
            expect(extractContentText(undefined)).toBe('')
        })
    })

    describe('extractVisualizationArtifact()', () => {
        it('returns null when no query is present', () => {
            expect(extractVisualizationArtifact(makeMessage({ innerInput: {} }))).toBeNull()
        })

        it('extracts a query and discriminates a saved artifact from the output short_id', () => {
            const artifact = extractVisualizationArtifact(
                makeMessage({
                    innerInput: { query: { kind: NodeKind.HogQLQuery, query: 'select 1' } },
                    rawOutput: { short_id: 'abc123', name: 'My insight' },
                })
            )
            expect(artifact).not.toBeNull()
            expect(artifact?.envelope.artifact_id).toBe('abc123')
            expect(artifact?.content.name).toBe('My insight')
        })
    })

    describe('extractSummarizePayload()', () => {
        it('returns null when not completed', () => {
            expect(
                extractSummarizePayload(makeMessage({ status: 'in_progress', rawOutput: { title: 'x' } }))
            ).toBeNull()
        })

        it('reads the payload off rawOutput on completion', () => {
            const payload = extractSummarizePayload(
                makeMessage({ rawOutput: { session_group_summary_id: 'sg-1', title: 'Summary' } })
            )
            expect(payload).toEqual({ session_group_summary_id: 'sg-1', title: 'Summary' })
        })
    })
})
