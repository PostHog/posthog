import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { SavedSessionRecordingPlaylistsResult } from '~/types'

import { recordingPlaylists } from '../__mocks__/recording_playlists'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { AddToCollectionModal } from './SessionRecordingsPlaylistSettings'

const emptyPlaylists: SavedSessionRecordingPlaylistsResult = {
    count: 0,
    next: null,
    previous: null,
    results: [],
}

const filterPlaylistsBySearch = (search: string | null): SavedSessionRecordingPlaylistsResult => {
    if (!search) {
        return recordingPlaylists
    }
    const term = search.toLowerCase()
    const results = recordingPlaylists.results.filter((p) =>
        (p.name || p.derived_name || '').toLowerCase().includes(term)
    )
    return { ...recordingPlaylists, count: results.length, results }
}

const StoryWrapper = ({ initialSearch }: { initialSearch?: string }): JSX.Element => {
    const { setIsAddToCollectionModalOpen, setAddToCollectionSearch, setSelectedRecordingsIds } =
        useActions(sessionRecordingsPlaylistLogic)

    useEffect(() => {
        setSelectedRecordingsIds(['rec-1', 'rec-2', 'rec-3'])
        setIsAddToCollectionModalOpen(true)
        if (initialSearch) {
            setAddToCollectionSearch(initialSearch)
        }
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="p-4 min-h-[600px]">
            <AddToCollectionModal />
            <div className="text-secondary text-xs">
                The modal renders into a portal. Inspect the page to see the dialog.
            </div>
        </div>
    )
}

const meta: Meta<typeof AddToCollectionModal> = {
    title: 'Replay/Components/AddToCollectionModal',
    component: AddToCollectionModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        testOptions: {
            viewport: { width: 800, height: 720 },
        },
    },
    decorators: [
        (Story) => (
            <BindLogic logic={sessionRecordingsPlaylistLogic} props={{ logicKey: 'storybook', onlyPinned: true }}>
                <Story />
            </BindLogic>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AddToCollectionModal>

export const NoSearchEntered: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/session_recording_playlists': (req, res, ctx) => {
                    const search = req.url.searchParams.get('search')
                    return res(ctx.json(filterPlaylistsBySearch(search)))
                },
            },
        })
        return <StoryWrapper />
    },
}

export const SearchWithResults: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/session_recording_playlists': (req, res, ctx) => {
                    const search = req.url.searchParams.get('search')
                    return res(ctx.json(filterPlaylistsBySearch(search)))
                },
            },
        })
        return <StoryWrapper initialSearch="nightly" />
    },
}

export const SearchWithNoResults: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/session_recording_playlists': (_req, res, ctx) => res(ctx.json(emptyPlaylists)),
            },
        })
        return <StoryWrapper initialSearch="no-match-for-this-term" />
    },
}

export const NoCollections: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/session_recording_playlists': (_req, res, ctx) => res(ctx.json(emptyPlaylists)),
            },
        })
        return <StoryWrapper />
    },
}
