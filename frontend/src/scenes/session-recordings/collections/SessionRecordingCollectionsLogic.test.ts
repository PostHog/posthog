import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import {
    DEFAULT_PLAYLIST_FILTERS,
    PLAYLISTS_PER_PAGE,
    sessionRecordingCollectionsLogic,
} from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

describe('sessionRecordingCollectionsLogic', () => {
    let logic: ReturnType<typeof sessionRecordingCollectionsLogic.build>
    const mockPlaylistsResponse = {
        count: 1,
        next: null,
        previous: null,
        results: ['List of playlists'],
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists': (req) => {
                    const { searchParams } = req.url
                    if (searchParams.get('date_to') === '2021-10-05') {
                        return [
                            200,
                            {
                                count: 1,
                                results: ['List of playlists filtered by dateTo'],
                            },
                        ]
                    } else if (searchParams.get('order') === 'last_modified_at') {
                        return [
                            200,
                            {
                                count: 1,
                                results: ['List of playlists filtered by order'],
                            },
                        ]
                    } else if (searchParams.get('date_from') === '-7d') {
                        return [
                            200,
                            {
                                count: 1,
                                results: ['List of playlists filtered by dateFrom'],
                            },
                        ]
                    } else if (
                        Number(searchParams.get('limit')) === PLAYLISTS_PER_PAGE &&
                        Number(searchParams.get('offset')) === PLAYLISTS_PER_PAGE
                    ) {
                        return [
                            200,
                            {
                                count: 1,
                                results: [`List of playlists filtered by page`],
                            },
                        ]
                    } else if (searchParams.get('search') === 'blah') {
                        return [
                            200,
                            {
                                count: 1,
                                results: [`List of playlists filtered by search`],
                            },
                        ]
                    } else if (searchParams.get('created_by') === '1') {
                        return [
                            200,
                            {
                                count: 1,
                                results: [`List of playlists filtered by createdBy`],
                            },
                        ]
                    } else if (searchParams.get('pinned')) {
                        return [
                            200,
                            {
                                count: 1,
                                results: [`List of playlists filtered by pinned`],
                            },
                        ]
                    }
                    return [200, mockPlaylistsResponse]
                },
            },
        })
        initKeaTests()
    })

    beforeEach(() => {
        logic = sessionRecordingCollectionsLogic()
        logic.mount()
    })

    describe('core assumptions', () => {
        it('loads session recordings after mounting', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadPlaylistsSuccess'])
                .toMatchValues({ playlists: mockPlaylistsResponse })
        })
    })

    describe('filters', () => {
        it('starts with default values', () => {
            expectLogic(logic).toMatchValues({ filters: DEFAULT_PLAYLIST_FILTERS })
        })

        describe('is set by setSavedPlaylistsFilters and loads filtered results and sets the url', () => {
            beforeEach(() => {
                router.actions.push(urls.replay(ReplayTabs.Playlists))
            })

            const params = {
                order: 'last_modified_at',
                search: 'blah',
                createdBy: 1,
                dateFrom: '-7d',
                dateTo: '2021-10-05',
                page: 2,
                pinned: true,
            }

            Object.entries(params).forEach(([key, value]) => {
                it(`can filter by ${key}`, async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setSavedPlaylistsFilters({
                            [key]: value,
                        })
                    })
                        .toFinishAllListeners()
                        .toMatchValues({
                            playlists: expect.objectContaining({
                                results: [`List of playlists filtered by ${key}`],
                            }),
                        })
                    expect(router.values.searchParams).toHaveProperty(key, value)
                })
            })
        })

        it('reads filters from the URL', async () => {
            router.actions.push(urls.replay(ReplayTabs.Playlists), {
                order: 'last_modified_at',
                search: 'blah',
                createdBy: 1,
                dateFrom: '-7d',
                dateTo: '2021-10-05',
                page: 2,
                pinned: true,
            })

            await expectLogic(logic)
                .toDispatchActions(['setSavedPlaylistsFilters'])
                .toMatchValues({
                    filters: {
                        order: 'last_modified_at',
                        search: 'blah',
                        createdBy: 1,
                        dateFrom: '-7d',
                        dateTo: '2021-10-05',
                        page: 2,
                        pinned: true,
                    },
                })
        })

        it('can remove search param', async () => {
            router.actions.push(urls.replay(ReplayTabs.Playlists))
            await expectLogic(logic, () => {
                logic.actions.setSavedPlaylistsFilters({ search: 'test', page: 1 })
                logic.actions.setSavedPlaylistsFilters({ search: undefined })
            }).toMatchValues({
                filters: {
                    page: 1,
                },
            })

            expect(router.values.searchParams).not.toHaveProperty('search')
            expect(router.values.searchParams).toHaveProperty('page', 1)
        })
    })
})
