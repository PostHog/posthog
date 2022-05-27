import {
    BehavioralEventType,
    CohortType,
    EventDefinition,
    EventType,
    FilterLogicalOperator,
    PropertyDefinition,
    PropertyOperator,
    TimeUnitType,
} from '~/types'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export const mockEvent: EventType = {
    id: 'my_id',
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
    elements_hash: null,
}

export const mockEventDefinitions: EventDefinition[] = [
    'event1',
    'test event',
    '$click',
    '$autocapture',
    'search',
    'other event',
    ...Array(50),
].map((name, index) => ({
    id: `uuid-${index}-foobar`,
    name: name || `misc-${index}-generated`,
    description: `${name || 'name generation'} is the best!`,
    query_usage_30_day: index * 3 + 1,
    volume_30_day: index * 13 + 2,
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
    volume_30_day: 2,
    query_usage_30_day: 1,
    is_event_property: true,
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
    is_event_property: (name || '').includes('$'),
}))

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
    name: 'Action',
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            id: 3,
            event: '$rageclick',
            tag_name: 'div',
            text: null,
            href: null,
            selector: null,
            url: 'test',
            name: 'Rage',
            url_matching: 'contains',
            properties: [],
        },
    ],
    created_at: '2022-01-24T21:32:38.360176Z',
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2022-01-24T21:32:38.359756Z',
    team_id: 1,
    created_by: null,
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
                    type: 'person',
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
