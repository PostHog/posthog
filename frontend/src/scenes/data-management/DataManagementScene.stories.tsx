import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, setFeatureFlags } from '~/mocks/browser'
import { DatabaseSchemaQueryResponse } from '~/queries/schema'

import { ingestionWarningsResponse } from './ingestion-warnings/__mocks__/ingestion-warnings-response'

const MOCK_DATABASE: DatabaseSchemaQueryResponse = {
    tables: {
        events: {
            type: 'posthog',
            id: 'events',
            name: 'events',
            fields: {
                uuid: { hogql_value: 'uuid', name: 'uuid', type: 'string', schema_valid: true },
                event: { hogql_value: 'event', name: 'event', type: 'string', schema_valid: true },
                properties: { hogql_value: 'properties', name: 'properties', type: 'json', schema_valid: true },
                timestamp: { hogql_value: 'timestamp', name: 'timestamp', type: 'datetime', schema_valid: true },
                distinct_id: { hogql_value: 'distinct_id', name: 'distinct_id', type: 'string', schema_valid: true },
                elements_chain: {
                    hogql_value: 'elements_chain',
                    name: 'elements_chain',
                    type: 'string',
                    schema_valid: true,
                },
                created_at: { hogql_value: 'created_at', name: 'created_at', type: 'datetime', schema_valid: true },
                pdi: {
                    hogql_value: 'pdi',
                    name: 'pdi',
                    type: 'lazy_table',
                    table: 'person_distinct_ids',
                    schema_valid: true,
                },
                poe: {
                    name: 'poe',
                    hogql_value: 'poe',
                    type: 'virtual_table',
                    table: 'events',
                    fields: ['id', 'created_at', 'properties'],
                    schema_valid: true,
                },
                person: {
                    hogql_value: 'person',
                    name: 'person',
                    type: 'field_traverser',
                    chain: ['pdi', 'person'],
                    schema_valid: true,
                },
                person_id: {
                    name: 'person_id',
                    hogql_value: 'person_id',
                    type: 'field_traverser',
                    chain: ['pdi', 'person_id'],
                    schema_valid: true,
                },
            },
        },
        persons: {
            type: 'posthog',
            id: 'persons',
            name: 'persons',
            fields: {
                id: { hogql_value: 'id', name: 'id', type: 'string', schema_valid: true },
                created_at: { hogql_value: 'created_at', name: 'created_at', type: 'datetime', schema_valid: true },
                properties: { hogql_value: 'properties', name: 'properties', type: 'json', schema_valid: true },
                is_identified: {
                    hogql_value: 'is_identified',
                    name: 'is_identified',
                    type: 'boolean',
                    schema_valid: true,
                },
                is_deleted: { hogql_value: 'is_deleted', name: 'is_deleted', type: 'boolean', schema_valid: true },
                version: { hogql_value: 'version', name: 'version', type: 'integer', schema_valid: true },
            },
        },
        person_distinct_ids: {
            type: 'posthog',
            id: 'person_distinct_ids',
            name: 'person_distinct_ids',
            fields: {
                distinct_id: { hogql_value: 'distinct_id', name: 'distinct_id', type: 'string', schema_valid: true },
                person_id: { hogql_value: 'person_id', name: 'person_id', type: 'string', schema_valid: true },
                is_deleted: { hogql_value: 'is_deleted', name: 'is_deleted', type: 'boolean', schema_valid: true },
                version: { hogql_value: 'version', name: 'version', type: 'integer', schema_valid: true },
                person: {
                    hogql_value: 'person',
                    name: 'person',
                    type: 'lazy_table',
                    table: 'persons',
                    schema_valid: true,
                },
            },
        },
        session_recording_events: {
            type: 'posthog',
            id: 'session_recording_events',
            name: 'session_recording_events',
            fields: {
                uuid: { hogql_value: 'uuid', name: 'uuid', type: 'string', schema_valid: true },
                timestamp: { hogql_value: 'timestamp', name: 'timestamp', type: 'datetime', schema_valid: true },
                distinct_id: { hogql_value: 'distinct_id', name: 'distinct_id', type: 'string', schema_valid: true },
                session_id: { hogql_value: 'session_id', name: 'session_id', type: 'string', schema_valid: true },
                window_id: { hogql_value: 'window_id', name: 'window_id', type: 'string', schema_valid: true },
                snapshot_data: {
                    hogql_value: 'snapshot_data',
                    name: 'snapshot_data',
                    type: 'json',
                    schema_valid: true,
                },
                created_at: { hogql_value: 'created_at', name: 'created_at', type: 'datetime', schema_valid: true },
                has_full_snapshot: {
                    hogql_value: 'has_full_snapshot',
                    name: 'has_full_snapshot',
                    type: 'boolean',
                    schema_valid: true,
                },
                events_summary: {
                    hogql_value: 'events_summary',
                    name: 'events_summary',
                    type: 'json',
                    schema_valid: true,
                },
                click_count: { hogql_value: 'click_count', name: 'click_count', type: 'integer', schema_valid: true },
                keypress_count: {
                    hogql_value: 'keypress_count',
                    name: 'keypress_count',
                    type: 'integer',
                    schema_valid: true,
                },
                timestamps_summary: {
                    hogql_value: 'timestamps_summary',
                    name: 'timestamps_summary',
                    type: 'datetime',
                    schema_valid: true,
                },
                first_event_timestamp: {
                    hogql_value: 'first_event_timestamp',
                    name: 'first_event_timestamp',
                    type: 'datetime',
                    schema_valid: true,
                },
                last_event_timestamp: {
                    hogql_value: 'last_event_timestamp',
                    name: 'last_event_timestamp',
                    type: 'datetime',
                    schema_valid: true,
                },
                urls: { hogql_value: 'urls', name: 'urls', type: 'string', schema_valid: true },
                pdi: {
                    hogql_value: 'pdi',
                    name: 'pdi',
                    type: 'lazy_table',
                    table: 'person_distinct_ids',
                    schema_valid: true,
                },
                person: {
                    hogql_value: 'person',
                    name: 'person',
                    type: 'field_traverser',
                    chain: ['pdi', 'person'],
                    schema_valid: true,
                },
                person_id: {
                    name: 'person_id',
                    hogql_value: 'person_id',
                    type: 'field_traverser',
                    chain: ['pdi', 'person_id'],
                    schema_valid: true,
                },
            },
        },
        cohort_people: {
            type: 'posthog',
            id: 'cohort_people',
            name: 'cohort_people',
            fields: {
                person_id: { hogql_value: 'person_id', name: 'person_id', type: 'string', schema_valid: true },
                cohort_id: { hogql_value: 'cohort_id', name: 'cohort_id', type: 'integer', schema_valid: true },
                sign: { hogql_value: 'sign', name: 'sign', type: 'integer', schema_valid: true },
                version: { hogql_value: 'version', name: 'version', type: 'integer', schema_valid: true },
                person: {
                    hogql_value: 'person',
                    name: 'person',
                    type: 'lazy_table',
                    table: 'persons',
                    schema_valid: true,
                },
            },
        },
        static_cohort_people: {
            type: 'posthog',
            id: 'static_cohort_people',
            name: 'static_cohort_people',
            fields: {
                person_id: { hogql_value: 'person_id', name: 'person_id', type: 'string', schema_valid: true },
                cohort_id: { hogql_value: 'cohort_id', name: 'cohort_id', type: 'integer', schema_valid: true },
                person: {
                    hogql_value: 'person',
                    name: 'person',
                    type: 'lazy_table',
                    table: 'persons',
                    schema_valid: true,
                },
            },
        },
        groups: {
            type: 'posthog',
            id: 'groups',
            name: 'groups',
            fields: {
                index: { hogql_value: 'index', name: 'index', type: 'integer', schema_valid: true },
                key: { hogql_value: 'key', name: 'key', type: 'string', schema_valid: true },
                created_at: { hogql_value: 'created_at', name: 'created_at', type: 'datetime', schema_valid: true },
                properties: { hogql_value: 'properties', name: 'properties', type: 'json', schema_valid: true },
            },
        },
    },
}

const meta: Meta = {
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ingestion_warnings/': () => {
                    return [200, ingestionWarningsResponse(dayjs('2023-02-15T16:00:00.000Z'))]
                },
            },
            post: {
                '/api/projects/:team_id/query/': (req) => {
                    if ((req.body as any).query.kind === 'DatabaseSchemaQuery') {
                        return [200, MOCK_DATABASE]
                    }
                },
            },
        }),
    ],
}
export default meta

export function IngestionWarnings(): JSX.Element {
    setFeatureFlags([FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED])
    useEffect(() => {
        router.actions.push(urls.ingestionWarnings())
    }, [])
    return <App />
}
