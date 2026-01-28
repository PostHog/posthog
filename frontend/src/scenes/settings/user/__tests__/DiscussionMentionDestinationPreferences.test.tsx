import { render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests, resetKeaDefaultLogic } from '~/test/init'

import { DiscussionMentionDestinationPreferences } from '../DiscussionMentionDestinationPreferences'
import type { ProjectWithDestinations } from '../discussionMentionDestinationsLogic'

const mockProjects: ProjectWithDestinations[] = [
    {
        id: 1,
        name: 'Project Alpha',
        destinations: [
            { id: 'dest-1', name: 'Slack Channel', type: 'slack', icon_url: 'https://example.com/slack.png' },
            { id: 'dest-2', name: 'Email Team', type: 'email', icon_url: null },
        ],
    },
    {
        id: 2,
        name: 'Project Beta',
        destinations: [{ id: 'dest-3', name: 'Discord Webhook', type: 'discord', icon_url: null }],
    },
]

describe('DiscussionMentionDestinationPreferences', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        resetKeaDefaultLogic()
    })

    it('renders loading state', async () => {
        useMocks({
            get: {
                '/api/users/@me/discussion_mention_destinations/': async () => {
                    await new Promise((resolve) => setTimeout(resolve, 1000))
                    return [200, { projects: [] }]
                },
                '/api/users/@me/': { notification_settings: {} },
            },
        })

        render(
            <Provider>
                <DiscussionMentionDestinationPreferences />
            </Provider>
        )

        expect(document.querySelector('.LemonSkeleton')).toBeInTheDocument()
    })

    it('renders empty state when no destinations', async () => {
        useMocks({
            get: {
                '/api/users/@me/discussion_mention_destinations/': { projects: [] },
                '/api/users/@me/': { notification_settings: {} },
            },
        })

        render(
            <Provider>
                <DiscussionMentionDestinationPreferences />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText(/No projects have discussion mention destinations configured/i)).toBeInTheDocument()
        })
    })

    it('renders destinations grouped by project', async () => {
        useMocks({
            get: {
                '/api/users/@me/discussion_mention_destinations/': { projects: mockProjects },
                '/api/users/@me/': { notification_settings: {} },
            },
        })

        render(
            <Provider>
                <DiscussionMentionDestinationPreferences />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Project Alpha')).toBeInTheDocument()
            expect(screen.getByText('Project Beta')).toBeInTheDocument()
        })

        expect(screen.getByText('Slack Channel', { exact: false })).toBeInTheDocument()
        expect(screen.getByText('Email Team', { exact: false })).toBeInTheDocument()
        expect(screen.getByText('Discord Webhook', { exact: false })).toBeInTheDocument()
    })

    it('shows all switches as enabled by default when no opt-outs exist', async () => {
        useMocks({
            get: {
                '/api/users/@me/discussion_mention_destinations/': { projects: mockProjects },
                '/api/users/@me/': { notification_settings: {} },
            },
        })

        render(
            <Provider>
                <DiscussionMentionDestinationPreferences />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByText('Project Alpha')).toBeInTheDocument()
        })

        const switches = document.querySelectorAll('.LemonSwitch input')
        switches.forEach((switchEl) => {
            expect(switchEl).toBeChecked()
        })
    })
})
