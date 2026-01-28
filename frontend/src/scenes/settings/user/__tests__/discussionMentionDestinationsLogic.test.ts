import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { type ProjectWithDestinations, discussionMentionDestinationsLogic } from '../discussionMentionDestinationsLogic'

describe('discussionMentionDestinationsLogic', () => {
    let logic: ReturnType<typeof discussionMentionDestinationsLogic.build>

    const mockProjects: ProjectWithDestinations[] = [
        {
            id: 1,
            name: 'Project 1',
            destinations: [
                { id: 'dest-1', name: 'Slack Channel', type: 'slack', icon_url: 'https://example.com/slack.png' },
                { id: 'dest-2', name: 'Email Team', type: 'email', icon_url: null },
            ],
        },
        {
            id: 2,
            name: 'Project 2',
            destinations: [{ id: 'dest-3', name: 'Discord Webhook', type: 'discord', icon_url: null }],
        },
    ]

    describe('loads projects from API', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/users/@me/discussion_mention_destinations/': {
                        projects: mockProjects,
                    },
                },
            })
            initKeaTests()
            logic = discussionMentionDestinationsLogic()
            logic.mount()
        })

        it('starts with empty projects', async () => {
            expect(logic.values.projects).toEqual([])
        })

        it('loads projects on mount', async () => {
            await expectLogic(logic).toDispatchActions(['loadProjects', 'loadProjectsSuccess'])
        })

        it('stores projects after loading', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                projectsLoading: false,
                projects: mockProjects,
            })
        })
    })

    describe('handles empty response', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/users/@me/discussion_mention_destinations/': {
                        projects: [],
                    },
                },
            })
            initKeaTests()
            logic = discussionMentionDestinationsLogic()
            logic.mount()
        })

        it('handles empty projects list', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                projectsLoading: false,
                projects: [],
            })
        })
    })
})
