/**
 * Hedgehog-themed test data for insight harness tests.
 *
 * Everything here uses real PostHog types (EventDefinition, PropertyDefinition, etc.)
 * so API mock responses match what the actual endpoints return.
 *
 * The data tells a story: a hedgehog rescue charity tracks rescues, adoptions,
 * vet visits, and website activity. Properties describe how, where, and by whom.
 */

import { EventDefinition, PropertyDefinition, PropertyType } from '~/types'

// ── Dates ───────────────────────────────────────────────────────────

const now = '2024-06-15T12:00:00.000Z'
const yesterday = '2024-06-14T09:30:00.000Z'
const lastWeek = '2024-06-08T14:22:00.000Z'
const lastMonth = '2024-05-15T11:00:00.000Z'

// ── Event definitions ───────────────────────────────────────────────

export const eventDefinitions: EventDefinition[] = [
    {
        id: 'evt-001',
        name: '$pageview',
        description: 'Page was viewed',
        tags: ['web', 'autocapture'],
        last_seen_at: now,
        created_at: lastMonth,
    },
    {
        id: 'evt-002',
        name: '$autocapture',
        description: 'Automatically captured DOM interaction',
        tags: ['web', 'autocapture'],
        last_seen_at: now,
        created_at: lastMonth,
    },
    {
        id: 'evt-003',
        name: '$identify',
        description: 'User identified themselves',
        tags: ['web'],
        last_seen_at: yesterday,
        created_at: lastMonth,
    },
    {
        id: 'evt-004',
        name: 'Saved a HedgeHog',
        description: 'A hedgehog was rescued and brought to safety',
        tags: ['rescue', 'core'],
        last_seen_at: now,
        created_at: lastMonth,
    },
    {
        id: 'evt-005',
        name: 'Adopted a HedgeHog',
        description: 'A hedgehog found its forever home',
        tags: ['adoption', 'core'],
        last_seen_at: yesterday,
        created_at: lastMonth,
    },
    {
        id: 'evt-006',
        name: 'Vet Visit Completed',
        description: 'Hedgehog completed a veterinary check-up',
        tags: ['health', 'core'],
        last_seen_at: yesterday,
        created_at: lastMonth,
    },
    {
        id: 'evt-007',
        name: 'Donated to Hedgehog Fund',
        description: 'Donation received for hedgehog care',
        tags: ['fundraising'],
        last_seen_at: lastWeek,
        created_at: lastMonth,
    },
    {
        id: 'evt-008',
        name: 'Hedgehog Spotted',
        description: 'A wild hedgehog was reported by a volunteer',
        tags: ['sighting', 'volunteer'],
        last_seen_at: now,
        created_at: lastMonth,
    },
    {
        id: 'evt-009',
        name: 'Volunteer Signed Up',
        description: 'New volunteer registered for hedgehog patrols',
        tags: ['volunteer'],
        last_seen_at: lastWeek,
        created_at: lastMonth,
    },
    {
        id: 'evt-010',
        name: 'Hedgehog Weighed',
        description: 'Hedgehog weight recorded during care',
        tags: ['health', 'tracking'],
        last_seen_at: yesterday,
        created_at: lastMonth,
    },
]

// ── Property definitions ────────────────────────────────────────────

export const propertyDefinitions: PropertyDefinition[] = [
    // Standard web properties
    {
        id: 'prop-001',
        name: '$browser',
        description: 'Browser used',
        tags: ['web'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-002',
        name: '$os',
        description: 'Operating system',
        tags: ['web'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-003',
        name: '$current_url',
        description: 'URL of the current page',
        tags: ['web'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-004',
        name: '$device_type',
        description: 'Device type',
        tags: ['web'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-005',
        name: '$screen_height',
        description: 'Screen height in pixels',
        tags: ['web'],
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },
    {
        id: 'prop-006',
        name: '$screen_width',
        description: 'Screen width in pixels',
        tags: ['web'],
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },

    // Hedgehog rescue properties
    {
        id: 'prop-100',
        name: 'rescue_method',
        description: 'How the hedgehog was rescued',
        tags: ['rescue'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-101',
        name: 'location',
        description: 'Where the hedgehog was found or event occurred',
        tags: ['rescue', 'sighting'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-102',
        name: 'hedgehog_name',
        description: 'Name given to the hedgehog',
        tags: ['core'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-103',
        name: 'weight_grams',
        description: 'Hedgehog weight in grams',
        tags: ['health'],
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },
    {
        id: 'prop-104',
        name: 'species',
        description: 'Hedgehog species',
        tags: ['core'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-105',
        name: 'health_status',
        description: 'Health condition at time of event',
        tags: ['health'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-106',
        name: 'donation_amount',
        description: 'Donation amount in GBP',
        tags: ['fundraising'],
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },
    {
        id: 'prop-107',
        name: 'volunteer_name',
        description: 'Name of the volunteer',
        tags: ['volunteer'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-108',
        name: 'season',
        description: 'Season when event occurred',
        tags: ['core'],
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'prop-109',
        name: 'is_baby',
        description: 'Whether the hedgehog is a hoglet',
        tags: ['core'],
        is_numerical: false,
        property_type: PropertyType.Boolean,
    },
]

// ── Property values ─────────────────────────────────────────────────
// Maps property names to their known values. Used by the auto-responder
// for breakdown queries and by the events/values endpoint.

export const propertyValues: Record<string, string[]> = {
    $browser: ['Chrome', 'Firefox', 'Safari', 'Edge'],
    $os: ['Mac OS X', 'Windows', 'Linux', 'iOS', 'Android'],
    $device_type: ['Desktop', 'Mobile', 'Tablet'],
    rescue_method: ['from road', 'from garden', 'from drain', 'from netting', 'brought by public'],
    location: ['London', 'Bristol', 'Edinburgh', 'Manchester', 'Oxford', 'Cambridge'],
    hedgehog_name: ['Spike', 'Bramble', 'Thistle', 'Hazel', 'Conker', 'Prickles', 'Nettle', 'Acorn'],
    species: ['European hedgehog', 'African pygmy hedgehog'],
    health_status: ['healthy', 'underweight', 'injured', 'dehydrated', 'critical'],
    season: ['spring', 'summer', 'autumn', 'winter'],
    is_baby: ['true', 'false'],
    volunteer_name: ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve'],
}

// ── Person properties (used by /persons/properties) ─────────────────

export const personProperties = [
    { id: 1, name: 'email', count: 42 },
    { id: 2, name: 'name', count: 38 },
    { id: 3, name: 'volunteer_since', count: 15 },
    { id: 4, name: 'hedgehogs_rescued', count: 12 },
    { id: 5, name: '$browser', count: 42 },
]

// ── Session property definitions ────────────────────────────────────

export const sessionPropertyDefinitions: PropertyDefinition[] = [
    {
        id: 'session-001',
        name: '$session_duration',
        description: 'Duration of the session in seconds',
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },
    {
        id: 'session-002',
        name: '$initial_utm_source',
        description: 'UTM source at session start',
        is_numerical: false,
        property_type: PropertyType.String,
    },
    {
        id: 'session-003',
        name: '$initial_referring_domain',
        description: 'Referring domain at session start',
        is_numerical: false,
        property_type: PropertyType.String,
    },
]

// ── Actions ─────────────────────────────────────────────────────────

export const actionDefinitions = [
    {
        id: 1,
        name: 'Rescued a hoglet',
        description: 'Triggered when a baby hedgehog is rescued',
        tags: ['rescue', 'core'],
        post_to_slack: true,
        slack_message_format: 'A hoglet was just rescued!',
        steps: [
            {
                id: 1,
                event: 'Saved a HedgeHog',
                properties: [{ type: 'event', key: 'is_baby', value: ['true'], operator: 'exact' }],
            },
        ],
        created_at: lastMonth,
        deleted: false,
        is_calculating: false,
        last_calculated_at: yesterday,
        team_id: 1,
        created_by: null,
        is_action: true as const,
        bytecode_error: null,
        pinned_at: null,
    },
    {
        id: 2,
        name: 'Large donation received',
        description: 'Donation over 100 GBP',
        tags: ['fundraising'],
        post_to_slack: true,
        slack_message_format: 'Big donation: {donation_amount} GBP!',
        steps: [
            {
                id: 2,
                event: 'Donated to Hedgehog Fund',
                properties: [{ type: 'event', key: 'donation_amount', value: '100', operator: 'gt' }],
            },
        ],
        created_at: lastMonth,
        deleted: false,
        is_calculating: false,
        last_calculated_at: yesterday,
        team_id: 1,
        created_by: null,
        is_action: true as const,
        bytecode_error: null,
        pinned_at: null,
    },
]

// ── Trends query response data ──────────────────────────────────────
// Pre-built series data for common queries. The auto-responder in mocks.ts
// generates these dynamically, but tests can also reference these directly
// for assertion values.

export const trendsSeries = {
    pageviews7d: {
        label: '$pageview',
        data: [120, 135, 98, 142, 156, 130, 145],
        days: ['2024-06-09', '2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15'],
        labels: [
            '9-Jun-2024',
            '10-Jun-2024',
            '11-Jun-2024',
            '12-Jun-2024',
            '13-Jun-2024',
            '14-Jun-2024',
            '15-Jun-2024',
        ],
    },
    rescues7d: {
        label: 'Saved a HedgeHog',
        data: [3, 5, 2, 4, 6, 3, 4],
        days: ['2024-06-09', '2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15'],
        labels: [
            '9-Jun-2024',
            '10-Jun-2024',
            '11-Jun-2024',
            '12-Jun-2024',
            '13-Jun-2024',
            '14-Jun-2024',
            '15-Jun-2024',
        ],
    },
    adoptions7d: {
        label: 'Adopted a HedgeHog',
        data: [1, 2, 0, 3, 1, 2, 1],
        days: ['2024-06-09', '2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15'],
        labels: [
            '9-Jun-2024',
            '10-Jun-2024',
            '11-Jun-2024',
            '12-Jun-2024',
            '13-Jun-2024',
            '14-Jun-2024',
            '15-Jun-2024',
        ],
    },
    rescuesByMethod: [
        { label: 'from road', data: [1, 2, 0, 1, 3, 1, 2], breakdown_value: 'from road' },
        { label: 'from garden', data: [2, 1, 1, 2, 1, 0, 1], breakdown_value: 'from garden' },
        { label: 'from drain', data: [0, 1, 1, 0, 1, 1, 0], breakdown_value: 'from drain' },
        { label: 'from netting', data: [0, 1, 0, 1, 0, 1, 1], breakdown_value: 'from netting' },
        { label: 'brought by public', data: [0, 0, 0, 0, 1, 0, 0], breakdown_value: 'brought by public' },
    ],
    rescuesByLocation: [
        { label: 'London', data: [1, 2, 1, 2, 3, 1, 2], breakdown_value: 'London' },
        { label: 'Bristol', data: [1, 1, 0, 1, 1, 1, 1], breakdown_value: 'Bristol' },
        { label: 'Edinburgh', data: [0, 1, 1, 0, 1, 0, 0], breakdown_value: 'Edinburgh' },
        { label: 'Manchester', data: [1, 1, 0, 1, 1, 1, 1], breakdown_value: 'Manchester' },
    ],
    donations7d: {
        label: 'Donated to Hedgehog Fund',
        data: [50, 120, 25, 200, 75, 150, 90],
        days: ['2024-06-09', '2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15'],
        labels: [
            '9-Jun-2024',
            '10-Jun-2024',
            '11-Jun-2024',
            '12-Jun-2024',
            '13-Jun-2024',
            '14-Jun-2024',
            '15-Jun-2024',
        ],
    },
}
