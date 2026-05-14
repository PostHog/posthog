import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { commands, executeCommand } from './generated/commands.js'
import type { Context } from './mcp-context.js'

function makeContext(responses: Record<string, unknown> = {}): Context {
    return {
        api: {
            request: async (apiCall: { path?: string }) => responses[apiCall.path ?? ''] ?? apiCall,
        },
        stateManager: {
            getProjectId: async () => '123',
        },
    } as unknown as Context
}

describe('generated command API call construction', () => {
    it('does not expose feature flag scheduled changes because the API is internal-only', () => {
        assert.deepEqual(
            Object.keys(commands['feature-flags'].subcommands).filter((name) => name.includes('scheduled')),
            []
        )
    })

    const cases: Array<{
        name: string
        command: string
        subcommand: string
        params: Record<string, unknown>
        expected: Record<string, unknown>
    }> = [
        {
            name: 'legacy LLM analytics list uses the evaluations endpoint',
            command: 'llm-analytics',
            subcommand: 'list',
            params: { search: 'quality' },
            expected: {
                method: 'GET',
                path: '/api/environments/123/evaluations/',
                query: { search: 'quality' },
            },
        },
        {
            name: 'events list maps q to event definition search',
            command: 'events',
            subcommand: 'list',
            params: { q: 'pageview', limit: 5 },
            expected: {
                method: 'GET',
                path: '/api/projects/123/event_definitions/',
                query: { search: 'pageview', limit: 5 },
            },
        },
        {
            name: 'experiment list legacy uses the current experiments endpoint',
            command: 'experiments',
            subcommand: 'list-legacy',
            params: { limit: 10 },
            expected: {
                method: 'GET',
                path: '/api/projects/123/experiments/',
                query: { limit: 10 },
            },
        },
        {
            name: 'projects list uses the projects endpoint',
            command: 'projects',
            subcommand: 'list',
            params: {},
            expected: { method: 'GET', path: '/api/projects/', query: {} },
        },
        {
            name: 'generic path params use --id and @current organization',
            command: 'projects',
            subcommand: 'view',
            params: { id: '456' },
            expected: { method: 'GET', path: '/api/organizations/@current/projects/456/' },
        },
        {
            name: 'usage list supports dashed path parameter names',
            command: 'usage',
            subcommand: 'list',
            params: { 'group-type-index': '0' },
            expected: { method: 'GET', path: '/api/projects/123/groups_types/0/metrics/' },
        },
        {
            name: 'subscription deliveries support subscription-id path parameter',
            command: 'subscriptions',
            subcommand: 'deliveries-list',
            params: { subscriptionId: 'sub-1', limit: 1 },
            expected: {
                method: 'GET',
                path: '/api/environments/123/subscriptions/sub-1/deliveries/',
                query: { limit: 1 },
            },
        },
        {
            name: 'skill file view requires explicit multi-part path parameters',
            command: 'llm-analytics',
            subcommand: 'skill-file-view',
            params: { skillName: 'assistant', filePath: 'README.md' },
            expected: {
                method: 'GET',
                path: '/api/environments/123/llm_skills/name/assistant/files/README.md/',
            },
        },
        {
            name: 'users view defaults to the current user',
            command: 'users',
            subcommand: 'view',
            params: {},
            expected: { method: 'GET', path: '/api/users/%40me/' },
        },
        {
            name: 'user home settings defaults to the current user',
            command: 'users',
            subcommand: 'home-settings-view',
            params: {},
            expected: { method: 'GET', path: '/api/user_home_settings/%40me/' },
        },
        {
            name: 'properties list maps eventName to event_names JSON',
            command: 'properties',
            subcommand: 'list',
            params: { type: 'event', eventName: '$pageview', includePredefinedProperties: true },
            expected: {
                method: 'GET',
                path: '/api/projects/123/property_definitions/',
                query: {
                    event_names: '["$pageview"]',
                    exclude_core_properties: false,
                    filter_by_event_names: true,
                    is_feature_flag: false,
                    type: 'event',
                    exclude_hidden: true,
                },
            },
        },
        {
            name: 'properties view uses the same direct property definitions endpoint',
            command: 'properties',
            subcommand: 'view',
            params: { type: 'person', limit: 1 },
            expected: {
                method: 'GET',
                path: '/api/projects/123/property_definitions/',
                query: { is_feature_flag: false, limit: 1, type: 'person', exclude_hidden: true },
            },
        },
        {
            name: 'session recordings list wraps params in RecordingsQuery',
            command: 'session-recordings',
            subcommand: 'list',
            params: { limit: 1 },
            expected: {
                method: 'POST',
                path: '/api/projects/123/query/',
                body: { query: { kind: 'RecordingsQuery', limit: 1 } },
            },
        },
        {
            name: 'sql view uses DatabaseSchemaQuery',
            command: 'sql',
            subcommand: 'view',
            params: { connectionId: 'abc' },
            expected: {
                method: 'POST',
                path: '/api/projects/123/query/',
                body: { query: { kind: 'DatabaseSchemaQuery', connectionId: 'abc' } },
            },
        },
        {
            name: 'template view maps --id to template_id',
            command: 'hog-functions',
            subcommand: 'templates-view',
            params: { id: 'template-meta-ads' },
            expected: { method: 'GET', path: '/api/projects/123/hog_function_templates/template-meta-ads/' },
        },
    ]

    for (const { name, command, subcommand, params, expected } of cases) {
        it(name, async () => {
            const apiCall = await executeCommand(makeContext(), command, subcommand, params)
            assert.deepEqual(apiCall, expected)
        })
    }

    it('notebook view resolves UUID ids from the list response to short_id', async () => {
        const apiCall = await executeCommand(
            makeContext({
                '/api/projects/123/notebooks/': {
                    results: [{ id: '0191a2a2-8a1a-0000-7329-387d983ff0c7', short_id: '0xWhdN5x' }],
                },
            }),
            'notebooks',
            'view',
            { id: '0191a2a2-8a1a-0000-7329-387d983ff0c7' }
        )

        assert.deepEqual(apiCall, { method: 'GET', path: '/api/projects/123/notebooks/0xWhdN5x/' })
    })

    it('playlist view resolves numeric ids from the list response to short_id', async () => {
        const apiCall = await executeCommand(
            makeContext({
                '/api/projects/123/session_recording_playlists/': {
                    results: [{ id: -1, short_id: 'synthetic-watch-history' }],
                },
            }),
            'session-recordings',
            'playlist-view',
            { id: '-1' }
        )

        assert.deepEqual(apiCall, {
            method: 'GET',
            path: '/api/projects/123/session_recording_playlists/synthetic-watch-history/',
        })
    })
})
