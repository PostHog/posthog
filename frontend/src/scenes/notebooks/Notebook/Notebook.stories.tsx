import { Meta } from '@storybook/react'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import notebook12345Json from './__mocks__/notebook-12345.json'

export default {
    title: 'Scenes-App/Notebooks',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-07-04', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/notebooks': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '01891c30-e217-0000-f8af-fd0995850693',
                            short_id: 'TzPqJ307',
                            title: 'testing my notebook wat',
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
                                                text: 'testing my notebook wat',
                                                type: 'text',
                                            },
                                        ],
                                    },
                                ],
                            },
                            version: 13,
                            deleted: false,
                            created_at: '2023-07-03T14:38:32.984546Z',
                            created_by: {
                                id: 1,
                                uuid: '0188ea22-05ae-0000-6d0b-d47602552d2c',
                                distinct_id: 'wnATPtp3kGKinrPUTgGGuR80MmuzrJLRwzGgtoJCt4V',
                                first_name: 'Paul',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                            },
                            last_modified_at: '2023-07-03T17:03:51.166530Z',
                            last_modified_by: {
                                id: 1,
                                uuid: '0188ea22-05ae-0000-6d0b-d47602552d2c',
                                distinct_id: 'wnATPtp3kGKinrPUTgGGuR80MmuzrJLRwzGgtoJCt4V',
                                first_name: 'Paul',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                            },
                        },
                    ],
                },
                'api/projects/:team_id/notebooks/12345': notebook12345Json,
            },
        }),
    ],
} as Meta

export function NotebooksList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.notebooks())
    }, [])
    return <App />
}

export function TextOnlyNotebook(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.notebook('12345'))
    }, [])
    return <App />
}

export function NotebookNotFound(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.notebook('abcde'))
    }, [])
    return <App />
}
