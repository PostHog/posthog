import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import type { shortLinksLogicType } from './shortLinksLogicType'

export interface ShortLink {
    key: string
    destination_url: string
    created_at: string
    updated_at: string
    expiration_date?: string
}

export interface NewShortLink {
    destination_url: string
    expiration_date?: string
}

export const shortLinksLogic = kea<shortLinksLogicType>([
    path(['scenes', 'short-links', 'shortLinksLogic']),
    actions({
        setNewLinkDestinationUrl: (url: string) => ({ url }),
        setNewLinkExpirationDate: (date: string | null) => ({ date }),
        createShortLink: true,
        deleteShortLink: (key: string) => ({ key }),
        setEditingLink: (link: ShortLink | null) => ({ link }),
        updateShortLink: (key: string, changes: Partial<ShortLink>) => ({ key, changes }),
    }),

    loaders(() => ({
        shortLinks: {
            __default: [] as ShortLink[],
            loadShortLinks: async () => {
                const response = await api.get('api/short_links/')
                return response.results as ShortLink[]
            },
        },
    })),

    reducers({
        newLink: [
            { destination_url: '', expiration_date: undefined } as NewShortLink,
            {
                setNewLinkDestinationUrl: (state, { url }) => ({ ...state, destination_url: url }),
                setNewLinkExpirationDate: (state, { date }) => ({ ...state, expiration_date: date || undefined }),
                createShortLink: () => ({ destination_url: '', expiration_date: undefined }),
            },
        ],
        editingLink: [
            null as ShortLink | null,
            {
                setEditingLink: (_, { link }) => link,
            },
        ],
    }),

    selectors({
        sortedShortLinks: [
            (s) => [s.shortLinks],
            (shortLinks): ShortLink[] => {
                return shortLinks ? [...shortLinks].sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf()) : []
            },
        ],
        activeShortLinks: [
            (s) => [s.sortedShortLinks],
            (sortedLinks): ShortLink[] => {
                const now = dayjs()
                return sortedLinks.filter((link) => !link.expiration_date || dayjs(link.expiration_date).isAfter(now))
            },
        ],
        expiredShortLinks: [
            (s) => [s.sortedShortLinks],
            (sortedLinks): ShortLink[] => {
                const now = dayjs()
                return sortedLinks.filter((link) => link.expiration_date && dayjs(link.expiration_date).isBefore(now))
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createShortLink: async () => {
            if (!values.newLink.destination_url) {
                return
            }
            await api.create('api/short_links/', values.newLink)
            actions.loadShortLinks()
        },
        deleteShortLink: async ({ key }) => {
            await api.delete(`api/short_links/${key}`)
            actions.loadShortLinks()
        },
        updateShortLink: async ({ key, changes }) => {
            await api.update(`api/short_links/${key}`, changes)
            actions.loadShortLinks()
            actions.setEditingLink(null)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadShortLinks()
    }),
])
