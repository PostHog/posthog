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
    events: [
        { key: 'uuid', type: 'string', schema_valid: true },
        { key: 'event', type: 'string', schema_valid: true },
        { key: 'properties', type: 'json', schema_valid: true },
        { key: 'timestamp', type: 'datetime', schema_valid: true },
        { key: 'distinct_id', type: 'string', schema_valid: true },
        { key: 'elements_chain', type: 'string', schema_valid: true },
        { key: 'created_at', type: 'datetime', schema_valid: true },
        { key: 'pdi', type: 'lazy_table', table: 'person_distinct_ids', schema_valid: true },
        {
            key: 'poe',
            type: 'virtual_table',
            table: 'events',
            fields: ['id', 'created_at', 'properties'],
            schema_valid: true,
        },
        { key: 'person', type: 'field_traverser', chain: ['pdi', 'person'], schema_valid: true },
        { key: 'person_id', type: 'field_traverser', chain: ['pdi', 'person_id'], schema_valid: true },
    ],
    persons: [
        { key: 'id', type: 'string', schema_valid: true },
        { key: 'created_at', type: 'datetime', schema_valid: true },
        { key: 'properties', type: 'json', schema_valid: true },
        { key: 'is_identified', type: 'boolean', schema_valid: true },
        { key: 'is_deleted', type: 'boolean', schema_valid: true },
        { key: 'version', type: 'integer', schema_valid: true },
    ],
    person_distinct_ids: [
        { key: 'distinct_id', type: 'string', schema_valid: true },
        { key: 'person_id', type: 'string', schema_valid: true },
        { key: 'is_deleted', type: 'boolean', schema_valid: true },
        { key: 'version', type: 'integer', schema_valid: true },
        { key: 'person', type: 'lazy_table', table: 'persons', schema_valid: true },
    ],
    session_recording_events: [
        { key: 'uuid', type: 'string', schema_valid: true },
        { key: 'timestamp', type: 'datetime', schema_valid: true },
        { key: 'distinct_id', type: 'string', schema_valid: true },
        { key: 'session_id', type: 'string', schema_valid: true },
        { key: 'window_id', type: 'string', schema_valid: true },
        { key: 'snapshot_data', type: 'json', schema_valid: true },
        { key: 'created_at', type: 'datetime', schema_valid: true },
        { key: 'has_full_snapshot', type: 'boolean', schema_valid: true },
        { key: 'events_summary', type: 'json', schema_valid: true },
        { key: 'click_count', type: 'integer', schema_valid: true },
        { key: 'keypress_count', type: 'integer', schema_valid: true },
        { key: 'timestamps_summary', type: 'datetime', schema_valid: true },
        { key: 'first_event_timestamp', type: 'datetime', schema_valid: true },
        { key: 'last_event_timestamp', type: 'datetime', schema_valid: true },
        { key: 'urls', type: 'string', schema_valid: true },
        { key: 'pdi', type: 'lazy_table', table: 'person_distinct_ids', schema_valid: true },
        { key: 'person', type: 'field_traverser', chain: ['pdi', 'person'], schema_valid: true },
        { key: 'person_id', type: 'field_traverser', chain: ['pdi', 'person_id'], schema_valid: true },
    ],
    cohort_people: [
        { key: 'person_id', type: 'string', schema_valid: true },
        { key: 'cohort_id', type: 'integer', schema_valid: true },
        { key: 'sign', type: 'integer', schema_valid: true },
        { key: 'version', type: 'integer', schema_valid: true },
        { key: 'person', type: 'lazy_table', table: 'persons', schema_valid: true },
    ],
    static_cohort_people: [
        { key: 'person_id', type: 'string', schema_valid: true },
        { key: 'cohort_id', type: 'integer', schema_valid: true },
        { key: 'person', type: 'lazy_table', table: 'persons', schema_valid: true },
    ],
    groups: [
        { key: 'index', type: 'integer', schema_valid: true },
        { key: 'key', type: 'string', schema_valid: true },
        { key: 'created_at', type: 'datetime', schema_valid: true },
        { key: 'properties', type: 'json', schema_valid: true },
    ],
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
export function Database(): JSX.Element {
    setFeatureFlags([FEATURE_FLAGS.DATA_WAREHOUSE])
    useEffect(() => {
        router.actions.push(urls.database())
    }, [])
    return <App />
}

export function IngestionWarnings(): JSX.Element {
    setFeatureFlags([FEATURE_FLAGS.INGESTION_WARNINGS_ENABLED])
    useEffect(() => {
        router.actions.push(urls.ingestionWarnings())
    }, [])
    return <App />
}
