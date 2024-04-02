import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { PersonType } from '~/types'

export const MOCK_PERSON: PersonType = {
    is_identified: true,
    distinct_ids: ['one', 'two', '123456', 'abcde'],
    properties: {
        email: 'test@posthog.com',
    },
    created_at: '2021-01-01T00:00:00.000Z',
}

const meta: Meta = {
    title: 'Scenes-App/Person',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/persons?distinct_id=one': { results: [MOCK_PERSON] },
            },
        }),
    ],
}

export default meta

export const NotFound: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.personByDistinctId('non-existent-id'))
    }, [])

    return <App />
}

export const MultipleDistinctIds: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.personByDistinctId(MOCK_PERSON.distinct_ids[0]))
    }, [])

    return <App />
}
