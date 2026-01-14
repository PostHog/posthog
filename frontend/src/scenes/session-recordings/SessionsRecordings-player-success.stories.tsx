import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { getAvailableProductFeatures } from '~/mocks/features'
import { MockSignature } from '~/mocks/utils'
import { ProductKey } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, SessionRecordingPlaylistType } from '~/types'

import { recordingPlaylists } from './__mocks__/recording_playlists'
import { recordings } from './__mocks__/recordings'

const generateManyRecordings = (count: number): Record<string, any>[] =>
    Array.from({ length: count }, (_, i) => ({
        ...recordings[i % recordings.length],
        id: `generated-recording-${i}`,
    }))

const playlist = (playlistId: string): SessionRecordingPlaylistType => {
    return {
        id: 29,
        short_id: playlistId,
        name: 'I am a playlist',
        derived_name: '(Untitled)',
        description: '',
        pinned: false,
        type: 'collection',
        created_at: '2023-07-31T16:24:38.956943Z',
        created_by: {
            id: 1,
            uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
            distinct_id: 'qs3Sp9pxE3nC827IbjDB6qNW6pD22X4tmGWwonM20p7',
            first_name: 'paul',
            email: 'paul@posthog.com',
            is_email_verified: true,
        },
        deleted: false,
        filters: {
            events: [],
            actions: [],
            date_to: null,
            date_from: '-7d',
            properties: [],
            console_logs: [],
            session_recording_duration: {
                key: 'duration',
                type: PropertyFilterType.Recording,
                value: 60,
                operator: PropertyOperator.GreaterThan,
            },
        },
        last_modified_at: '2023-07-31T16:34:15.297322Z',
        last_modified_by: {
            id: 1,
            uuid: '01896512-b4e6-0000-3add-7143ff5174c5',
            distinct_id: 'qs3Sp9pxE3nC827IbjDB6qNW6pD22X4tmGWwonM20p7',
            first_name: 'paul',
            email: 'paul@posthog.com',
            is_email_verified: true,
        },
        recordings_counts: {
            saved_filters: {
                count: 10,
                watched_count: 4,
                has_more: true,
                increased: true,
            },
            collection: {
                count: 10,
                watched_count: 5,
            },
        },
    }
}

const sceneUrl = (url: string, searchParams: Record<string, any> = {}): string =>
    combineUrl(url, {
        pause: true,
        t: 7,
        ...searchParams,
    }).url

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Success',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        waitForSelector: '.PlayerFrame__content .replayer-wrapper iframe',
        pageUrl: urls.replay(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 7 }],
                '/api/environments/:team_id/session_recordings': (req) => {
                    const version = req.url.searchParams.get('version')
                    return [
                        200,
                        {
                            has_next: false,
                            results: recordings,
                            version,
                        },
                    ]
                },
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const playlistId = req.params.playlist_id as string

                    return [200, playlist(playlistId)]
                },
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/recordings': (req) => {
                    const playlistId = req.params.playlist_id
                    const response = playlistId === '1234567' ? recordings : []
                    return [200, { has_next: false, results: response, version: 1 }]
                },
                '/api/environments/:team_id/session_recordings/:id/snapshots': (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob_v2') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }
                    // with no source requested should return sources
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2023-08-11T12:03:36.097000Z',
                                    end_timestamp: '2023-08-11T12:04:52.268000Z',
                                    blob_key: '0',
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                'api/projects/:team/notebooks': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
            patch: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id': (req) => {
                    const playlistId = req.params.playlist_id as string
                    const body = req.body as Partial<SessionRecordingPlaylistType>
                    return [200, { ...playlist(playlistId), ...body }]
                },
            },
            post: {
                '/api/projects/:team_id/session_recording_playlists/:playlist_id/playlist_viewed': [
                    200,
                    { success: true },
                ],
                '/api/environments/:team_id/session_recording_playlists/:playlist_id/playlist_viewed': [
                    200,
                    { success: true },
                ],
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>

                    if (body.query.kind === 'HogQLQuery' && body.query.query.includes('$session_id as session_id')) {
                        return res(
                            ctx.json({
                                results: recordings.map((r) => [
                                    r.id,
                                    'NG',
                                    'Chrome',
                                    'Desktop',
                                    'Mac OS X',
                                    'Mac OS X',
                                    'google.com',
                                    null,
                                    null,
                                    'https://example.com',
                                ]),
                            })
                        )
                    }

                    if (body.query.kind === 'EventsQuery' && body.query.properties.length === 1) {
                        return res(ctx.json(recordingEventsJson))
                    }

                    // default to an empty response or we duplicate information
                    return res(ctx.json({ results: [] }))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const RecentRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replay()) },
}

export const RecordingsPlayListNoPinnedRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replayPlaylist('abcdefg')) },
}

export const RecordingsPlayListWithPinnedRecordings: Story = {
    parameters: { pageUrl: sceneUrl(urls.replayPlaylist('1234567')) },
}

export const SecondRecordingInList: Story = {
    parameters: { pageUrl: sceneUrl(urls.replay(), { sessionRecordingId: recordings[1].id }) },
}

export const RecentRecordingsEmpty: Story = {
    parameters: {
        pageUrl: sceneUrl(urls.replay()),
        waitForSelector: undefined,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings': () => [
                    200,
                    { has_next: false, results: [], version: '1' },
                ],
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                'api/projects/:team/notebooks': { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                '/api/environments/:team_id/query': () => [200, { results: [] }],
            },
        }),
    ],
}

export const RecentRecordingsWide: Story = {
    parameters: {
        pageUrl: sceneUrl(urls.replay(), { sessionRecordingId: recordings[0].id }),
        testOptions: {
            viewport: { width: 1300, height: 720 },
        },
    },
}
RecentRecordingsWide.tags = ['test-skip']

export const RecentRecordingsNarrow: Story = {
    parameters: {
        pageUrl: sceneUrl(urls.replay(), { sessionRecordingId: recordings[0].id }),
        testOptions: {
            viewport: { width: 568, height: 1024 },
        },
    },
}
RecentRecordingsNarrow.tags = ['test-skip']

const userSeenReplayIntroMock = (): MockSignature => [
    200,
    {
        ...MOCK_DEFAULT_USER,
        has_seen_product_intro_for: { [ProductKey.SESSION_REPLAY]: true },
        organization: { ...MOCK_DEFAULT_ORGANIZATION, available_product_features: getAvailableProductFeatures() },
    },
]

const manyRecordingsMock: MockSignature = (req) => {
    const version = req.url.searchParams.get('version')
    return [200, { has_next: false, results: generateManyRecordings(25), version }]
}

const filtersExpandedStory = (extraMocks: Record<string, any> = {}): StoryFn => {
    const Story: StoryFn = () => {
        useStorybookMocks({
            get: {
                '/api/users/@me/': userSeenReplayIntroMock,
                ...extraMocks,
            },
        })
        router.actions.push(sceneUrl(urls.replay(), { showFilters: true }))
        return <App />
    }
    return Story
}

export const FiltersExpanded: StoryFn = filtersExpandedStory()
FiltersExpanded.parameters = {
    waitForSelector: '[data-attr="session-recordings-filters-tab"]',
}

export const FiltersExpandedLotsOfResults: StoryFn = filtersExpandedStory({
    '/api/environments/:team_id/session_recordings': manyRecordingsMock,
})
FiltersExpandedLotsOfResults.parameters = {
    waitForSelector: '[data-attr="session-recordings-filters-tab"]',
}

export const FiltersExpandedLotsOfResultsNarrow: StoryFn = filtersExpandedStory({
    '/api/environments/:team_id/session_recordings': manyRecordingsMock,
})
FiltersExpandedLotsOfResultsNarrow.parameters = {
    waitForSelector: '[data-attr="session-recordings-filters-tab"]',
    testOptions: {
        viewport: { width: 568, height: 1024 },
    },
}

const cinemaModeStory = (mocks: Record<string, any> = {}): StoryFn => {
    const Story: StoryFn = () => {
        const { setIsCinemaMode } = useActions(playerSettingsLogic)
        useStorybookMocks({ get: mocks })
        useEffect(() => setIsCinemaMode(true), [setIsCinemaMode])
        router.actions.push(sceneUrl(urls.replay(), { sessionRecordingId: recordings[0].id }))
        return <App />
    }
    return Story
}

const cinemaModeWideParameters = { testOptions: { viewport: { width: 1300, height: 720 } } }
const cinemaModeNarrowParameters = { testOptions: { viewport: { width: 568, height: 1024 } } }

export const CinemaModeWithIntro: StoryFn = cinemaModeStory()
CinemaModeWithIntro.parameters = cinemaModeWideParameters

export const CinemaModeSeenIntro: StoryFn = cinemaModeStory({ '/api/users/@me/': userSeenReplayIntroMock })
CinemaModeSeenIntro.parameters = cinemaModeWideParameters

export const CinemaModeWithIntroNarrow: StoryFn = cinemaModeStory()
CinemaModeWithIntroNarrow.parameters = cinemaModeNarrowParameters

export const CinemaModeSeenIntroNarrow: StoryFn = cinemaModeStory({ '/api/users/@me/': userSeenReplayIntroMock })
CinemaModeSeenIntroNarrow.parameters = cinemaModeNarrowParameters
