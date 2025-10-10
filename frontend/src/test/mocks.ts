import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import {
    AccessControlLevel,
    BehavioralEventType,
    CohortType,
    EventDefinition,
    EventType,
    FilterLogicalOperator,
    IntegrationType,
    PropertyDefinition,
    PropertyFilterType,
    PropertyOperator,
    SlackChannelType,
    SubscriptionType,
    TimeUnitType,
    UserBasicType,
} from '~/types'

export const mockBasicUser: UserBasicType = {
    id: 0,
    uuid: '1234',
    distinct_id: '1234',
    first_name: 'Tim',
    email: 'tim@posthog.com',
}

export const mockEvent: EventType = {
    id: 'my_id',
    distinct_id: 'distinct_id',
    properties: {
        $os: 'Mac OS X',
        $device_type: 'Desktop',
    },
    event: 'event1',
    timestamp: '2022-02-24T09:19:56.920000+00:00',
    person: {
        is_identified: true,
        distinct_ids: ['abcde'],
        properties: {
            email: 'alex@posthog.com',
        },
    },
    elements: [],
    elements_chain: '',
}

export const mockEventDefinitions: EventDefinition[] = [
    'event1',
    'test event',
    '$click',
    '$autocapture',
    'search term',
    'other event',
    ...Array(150),
].map((name, index) => ({
    id: `uuid-${index}-foobar`,
    name: name || `misc-${index}-generated`,
    description: `${name || 'name generation'} is the best!`,
    tags: [],
}))

export const mockEventPropertyDefinition = {
    id: '017e8d9e-4241-0000-57ad-3a7237ffdb8e',
    name: '$active_feature_flags',
    description: '',
    tags: [],
    is_numerical: false,
    updated_at: '2022-01-24T21:32:38.359756Z',
    updated_by: null,
    is_seen_on_filtered_events: true,
    property_type: undefined,
}

export const mockEventPropertyDefinitions: PropertyDefinition[] = [
    'prop1',
    'purchase_value',
    '$click',
    '$browser',
    'browser_no_dollar_not_on_event',
    'is_admin',
    ...Array(50),
].map((name, index) => ({
    ...mockEventPropertyDefinition,
    id: `uuid-${index}-foobar`,
    name: name || `misc-${index}-generated`,
    description: `${name || 'name generation'} is the best!`,
    is_seen_on_filtered_events: (name || '').includes('$'),
}))

export const mockSessionPropertyDefinitions: PropertyDefinition[] = ['$session_duration', '$initial_utm_source'].map(
    (name) => ({
        ...mockEventPropertyDefinition,
        id: name,
        name: name,
        description: `${name} is the best!`,
    })
)

export const mockPersonProperty = {
    name: '$browser_version',
    count: 1,
}

export const mockGroup = {
    name: 'name',
    count: 3,
}

export const mockElement = {
    name: 'selector',
}

export const mockActionDefinition = {
    id: 3,
    name: 'Action with a moderately long name',
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            id: 3,
            event: '$rageclick',
            tag_name: 'div',
            text: null,
            href: null,
            selector: '.buy-now-important-on-sale-button',
            url: 'test',
            name: 'Rage',
            url_matching: 'contains',
            properties: [],
        },
        {
            id: 4,
            event: null, // All events
            properties: [{ type: 'property', key: '$geoip_country_code', value: ['US', 'DE'], operator: 'exact' }],
        },
    ],
    created_at: '2022-01-24T21:32:38.360176Z',
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2022-01-24T21:32:38.359756Z',
    team_id: 1,
    created_by: null,
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
}

export const mockCohort: CohortType = {
    id: 1,
    name: 'Cohort',
    count: 1,
    groups: [
        {
            id: 'a',
            name: 'Properties Group',
            count: 1,
            matchType: PROPERTY_MATCH_TYPE,
            properties: [
                {
                    key: '$geoip_continent_name',
                    type: PropertyFilterType.Person,
                    value: ['Oceania'],
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    ],
    filters: {
        properties: {
            id: '39777',
            type: FilterLogicalOperator.Or,
            values: [
                {
                    id: '70427',
                    type: FilterLogicalOperator.Or,
                    values: [
                        {
                            type: BehavioralFilterKey.Behavioral,
                            value: BehavioralEventType.PerformEvent,
                            event_type: TaxonomicFilterGroupType.Events,
                            time_value: 30,
                            time_interval: TimeUnitType.Day,
                            key: 'dashboard date range changed',
                            negation: true,
                        },
                    ],
                },
            ],
        },
    },
}

export const mockSubscription: SubscriptionType = {
    id: 1,
    title: 'My example subscription',
    target_type: 'email',
    target_value: 'ben@posthog.com,geoff@other-company.com',
    frequency: 'monthly',
    interval: 2,
    start_date: '2022-01-01T00:09:00',
    byweekday: ['wednesday'],
    bysetpos: 1,
    summary: 'sent every month on the first wednesday',
    created_at: '2022-01-01T00:09:00',
    updated_at: '2022-01-01T00:09:00',
}

export const createMockSubscription = (args: Partial<SubscriptionType> = {}): SubscriptionType => ({
    ...mockSubscription,
    ...args,
})

export const mockIntegration: IntegrationType = {
    id: 1,
    kind: 'slack',
    config: {
        team: {
            id: '123',
            name: 'PostHog',
        },
    },
    icon_url: '',
    display_name: '',
    created_at: '2022-01-01T00:09:00',
    created_by: mockBasicUser,
}

export const mockSlackChannel: SlackChannelType = {
    id: 'C1234',
    name: '#general',
    is_private: false,
    is_ext_shared: false,
    is_member: false,
}

export const mockSlackChannels: SlackChannelType[] = [
    {
        id: 'C1',
        name: 'general',
        is_private: false,
        is_ext_shared: false,
        is_member: false,
    },
    {
        id: 'C2',
        name: 'dev',
        is_private: false,
        is_ext_shared: false,
        is_member: true,
    },
    {
        id: 'C3',
        name: 'pineapple-conspiracies',
        is_private: true,
        is_ext_shared: false,
        is_member: true,
    },
    {
        id: 'C4',
        name: 'external-community',
        is_private: false,
        is_ext_shared: true,
        is_member: false,
    },
]
