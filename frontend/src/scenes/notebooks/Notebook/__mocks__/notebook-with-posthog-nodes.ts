import { NotebookType } from '~/types'

export const notebookWithPostHogNodes = {
    short_id: 'Ww5V54e0',
    title: 'A notebook with one of each',
    content: {
        type: 'doc',
        content: [
            {
                type: 'heading',
                attrs: {
                    level: 1,
                },
                content: [
                    {
                        text: 'A notebook with one of each',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'Insight',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-insight',
                attrs: {
                    id: 'pPHLOPFW',
                },
            },
            {
                type: 'paragraph',
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'Query',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-query',
                attrs: {
                    query: {
                        full: true,
                        kind: 'DataTableNode',
                        source: {
                            kind: 'HogQLQuery',
                            query: '   select event,\n          person.properties.email,\n          properties.$browser,\n          count()\n     from events\n    where timestamp > now () - interval 1 day\n      and person.properties.email is not null\n group by event,\n          properties.$browser,\n          person.properties.email\n order by count() desc\n    limit 100',
                        },
                    },
                    height: 500,
                },
            },
            {
                type: 'paragraph',
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'events table',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-query',
                attrs: {
                    query: {
                        full: true,
                        kind: 'DataTableNode',
                        source: {
                            kind: 'EventsQuery',
                            after: '-24h',
                            limit: 100,
                            select: [
                                '*',
                                'event',
                                'person',
                                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                                'properties.$lib',
                                'timestamp',
                            ],
                            properties: [
                                {
                                    key: '$browser',
                                    type: 'event',
                                    value: 'Chrome',
                                    operator: 'exact',
                                },
                            ],
                        },
                    },
                    height: 500,
                },
            },
            {
                type: 'paragraph',
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'playlist',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-recording-playlist',
                attrs: {
                    height: 'calc(100vh - 20rem)',
                },
            },
            {
                type: 'paragraph',
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'Flags ',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-feature-flag',
                attrs: {
                    id: '40',
                },
            },
            {
                type: 'heading',
                attrs: {
                    level: 2,
                },
                content: [
                    {
                        text: 'Person',
                        type: 'text',
                    },
                ],
            },
            {
                type: 'ph-query',
                attrs: {
                    query: {
                        full: false,
                        kind: 'DataTableNode',
                        source: {
                            kind: 'PersonsNode',
                        },
                        propertiesViaUrl: true,
                    },
                    height: 500,
                },
            },
            {
                type: 'paragraph',
            },
        ],
    },
    version: 32,
    created_at: '2023-07-11T17:08:00.598008Z',
    created_by: {
        id: 1,
        uuid: '01894532-408b-0000-9cff-db4bcc38a8cb',
        distinct_id: 'zgpvnzy52OiJQ19kLhGEVEABkDHcEZr59buGsmzTNNX',
        first_name: 'asdasfasfasda',
        email: 'paul@posthog.com',
        is_email_verified: false,
    },
    last_modified_at: '2023-07-11T18:09:45.141861Z',
    last_modified_by: {
        id: 1,
        uuid: '01894532-408b-0000-9cff-db4bcc38a8cb',
        distinct_id: 'zgpvnzy52OiJQ19kLhGEVEABkDHcEZr59buGsmzTNNX',
        first_name: 'asdasfasfasda',
        email: 'paul@posthog.com',
        is_email_verified: false,
    },
} satisfies NotebookType
