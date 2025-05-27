import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/Persons & Groups',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
    decorators: [],
}
export default meta

export const PersonsEmpty: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.persons())
    }, [])
    return <App />
}

export const Persons: StoryFn = () => {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': (req) => {
                const query = (req.body as any)?.query
                // Check if it's a DataTableNode query, which is used for Events/Exceptions tabs
                if (query && query.kind === 'ActorsQuery') {
                    return [
                        200,
                        {
                            columns: ['person_display_name -- Person', 'id', 'created_at', 'person.$delete'],
                            results: [
                                [
                                    {
                                        display_name: 'george@of.the.jungle.com',
                                        id: '741cc6c0-7c48-55f2-9b58-1b648a381c9e',
                                    },
                                    '741cc6c0-7c48-55f2-9b58-1b648a381c9e',
                                    '2023-05-08T15:49:50-07:00',
                                    1,
                                ],
                                [
                                    {
                                        display_name: 'george@harrison.com',
                                        id: '2bc35dc9-6dfb-5d18-90e4-a05b9d5d9dbf',
                                    },
                                    '2bc35dc9-6dfb-5d18-90e4-a05b9d5d9dbf',
                                    '2023-05-08T15:49:38-07:00',
                                    1,
                                ],
                            ], // Provide appropriate mock data for your DataTableNode queries
                            hasMore: false,
                            is_cached: true,
                            cache_key: 'test-datatable',
                            calculation_trigger: null,
                            error: '',
                            query_status: null,
                        },
                    ]
                }
                // Fallback for other POST /api/query calls that might not be DataTableNode
                // For example, if other components on this page make different query calls.
                // You might need to make this more specific if there are multiple non-DataTableNode POSTs.
                return [200, { results: [], message: 'Generic POST to /api/query mock for PersonSceneStory' }]
            },
        },
    })

    useEffect(() => {
        router.actions.push(urls.persons())
    }, [])
    return <App />
}

export const Cohorts: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.cohorts())
    }, [])
    return <App />
}

export const Groups: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.groups(0))
    }, [])
    return <App />
}
