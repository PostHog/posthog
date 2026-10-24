import type { Dayjs } from 'lib/dayjs'

import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    type SampleIds,
    type SampleRowsSource,
    buildSampleRows,
    samplePersonDisplayName,
    samplePropertyValue,
} from '~/queries/nodes/DataTable/sampleRows'

interface SampleEvent {
    event: string
    email: string
    properties: Record<string, string | null>
    minutesAgo: number
}

const WEB = { $lib: 'web', $browser: 'Chrome', $os: 'Mac OS X' }

const SAMPLE_EVENTS: SampleEvent[] = [
    {
        event: '$pageview',
        email: 'alice@example.com',
        properties: { ...WEB, $current_url: 'https://example.com/pricing', $pathname: '/pricing', $screen_name: null },
        minutesAgo: 1,
    },
    {
        event: 'user signed up',
        email: 'bob@example.com',
        properties: { ...WEB, $current_url: 'https://example.com/signup', $pathname: '/signup', $screen_name: null },
        minutesAgo: 3,
    },
    {
        event: '$screen',
        email: 'carol@example.com',
        properties: {
            $lib: 'posthog-ios',
            $os: 'iOS',
            $browser: null,
            $current_url: null,
            $pathname: null,
            $screen_name: 'HomeScreen',
        },
        minutesAgo: 6,
    },
    {
        event: 'clicked button',
        email: 'alice@example.com',
        properties: {
            ...WEB,
            $current_url: 'https://example.com/dashboard',
            $pathname: '/dashboard',
            $screen_name: null,
        },
        minutesAgo: 9,
    },
    {
        event: 'purchase completed',
        email: 'dave@example.com',
        properties: {
            $lib: 'posthog-node',
            $os: null,
            $browser: null,
            $current_url: null,
            $pathname: null,
            $screen_name: null,
        },
        minutesAgo: 12,
    },
    {
        event: '$pageview',
        email: 'erin@example.com',
        properties: { ...WEB, $current_url: 'https://example.com/docs', $pathname: '/docs', $screen_name: null },
        minutesAgo: 15,
    },
]

const URL_OR_SCREEN_COLUMN = 'coalesce(properties.$current_url, properties.$screen_name)'

function sampleValue(key: string, sample: SampleEvent, ids: SampleIds, now: Dayjs): unknown {
    const timestamp = now.subtract(sample.minutesAgo, 'minute').toISOString()

    if (key === '*') {
        return {
            uuid: ids.eventId,
            event: sample.event,
            distinct_id: ids.distinctId,
            properties: sample.properties,
            timestamp,
        }
    }
    if (key === 'event') {
        return sample.event
    }
    if (key === 'timestamp') {
        return timestamp
    }
    if (key === 'distinct_id') {
        return ids.distinctId
    }
    if (key === 'person_display_name') {
        return samplePersonDisplayName(sample.email, ids)
    }
    if (key === 'person') {
        return { uuid: ids.personId, distinct_id: ids.distinctId, properties: { email: sample.email } }
    }
    if (key === URL_OR_SCREEN_COLUMN) {
        return sample.properties.$current_url ?? sample.properties.$screen_name
    }
    return samplePropertyValue(key, sample.properties)
}

export function buildSampleEventRows(columns: string[], now: Dayjs): (DataTableRow & { result: unknown[] })[] {
    return buildSampleRows(SAMPLE_EVENTS, columns, (key, sample, ids) => sampleValue(key, sample, ids, now))
}

export const SAMPLE_EVENTS_SOURCE: SampleRowsSource = {
    buildRows: buildSampleEventRows,
    // pinned: the data-attr value is an autocapture selector, so renaming it breaks dashboards
    dataAttr: 'events-table-sample-data',
    hiddenColumns: [],
}
