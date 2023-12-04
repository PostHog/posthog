import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, setFeatureFlags } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { DatabaseSchemaQueryResponse } from '~/queries/schema'
import { AvailableFeature } from '~/types'

import { ingestionWarningsResponse } from './ingestion-warnings/__mocks__/ingestion-warnings-response'

const MOCK_DATABASE: DatabaseSchemaQueryResponse = {
    events: [
        { key: 'uuid', type: 'string' },
        { key: 'event', type: 'string' },
        { key: 'properties', type: 'json' },
        { key: 'timestamp', type: 'datetime' },
        { key: 'distinct_id', type: 'string' },
        { key: 'elements_chain', type: 'string' },
        { key: 'created_at', type: 'datetime' },
        { key: 'pdi', type: 'lazy_table', table: 'person_distinct_ids' },
        { key: 'poe', type: 'virtual_table', table: 'events', fields: ['id', 'created_at', 'properties'] },
        { key: 'person', type: 'field_traverser', chain: ['pdi', 'person'] },
        { key: 'person_id', type: 'field_traverser', chain: ['pdi', 'person_id'] },
    ],
    persons: [
        { key: 'id', type: 'string' },
        { key: 'created_at', type: 'datetime' },
        { key: 'properties', type: 'json' },
        { key: 'is_identified', type: 'boolean' },
        { key: 'is_deleted', type: 'boolean' },
        { key: 'version', type: 'integer' },
    ],
    person_distinct_ids: [
        { key: 'distinct_id', type: 'string' },
        { key: 'person_id', type: 'string' },
        { key: 'is_deleted', type: 'boolean' },
        { key: 'version', type: 'integer' },
        { key: 'person', type: 'lazy_table', table: 'persons' },
    ],
    session_recording_events: [
        { key: 'uuid', type: 'string' },
        { key: 'timestamp', type: 'datetime' },
        { key: 'distinct_id', type: 'string' },
        { key: 'session_id', type: 'string' },
        { key: 'window_id', type: 'string' },
        { key: 'snapshot_data', type: 'json' },
        { key: 'created_at', type: 'datetime' },
        { key: 'has_full_snapshot', type: 'boolean' },
        { key: 'events_summary', type: 'json' },
        { key: 'click_count', type: 'integer' },
        { key: 'keypress_count', type: 'integer' },
        { key: 'timestamps_summary', type: 'datetime' },
        { key: 'first_event_timestamp', type: 'datetime' },
        { key: 'last_event_timestamp', type: 'datetime' },
        { key: 'urls', type: 'string' },
        { key: 'pdi', type: 'lazy_table', table: 'person_distinct_ids' },
        { key: 'person', type: 'field_traverser', chain: ['pdi', 'person'] },
        { key: 'person_id', type: 'field_traverser', chain: ['pdi', 'person_id'] },
    ],
    cohort_people: [
        { key: 'person_id', type: 'string' },
        { key: 'cohort_id', type: 'integer' },
        { key: 'sign', type: 'integer' },
        { key: 'version', type: 'integer' },
        { key: 'person', type: 'lazy_table', table: 'persons' },
    ],
    static_cohort_people: [
        { key: 'person_id', type: 'string' },
        { key: 'cohort_id', type: 'integer' },
        { key: 'person', type: 'lazy_table', table: 'persons' },
    ],
    groups: [
        { key: 'index', type: 'integer' },
        { key: 'key', type: 'string' },
        { key: 'created_at', type: 'datetime' },
        { key: 'properties', type: 'json' },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
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
    useAvailableFeatures([AvailableFeature.EXPERIMENTATION])
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
