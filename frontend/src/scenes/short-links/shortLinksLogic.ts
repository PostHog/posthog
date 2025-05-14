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
    custom_key?: string
    tags?: string[]
    comments?: string
    folder?: string
    password?: string
    og_title?: string
    og_description?: string
    og_image?: File | string
    utm_params?: Record<string, string>
    targeting?: Record<string, any>
}

export interface NewShortLink {
    destination_url: string
    expiration_date?: string
    custom_key?: string
    tags?: string[]
    comments?: string
    folder?: string
    password?: string
    og_title?: string
    og_description?: string
    og_image: File | string | null
    utm_params?: Record<string, string>
    targeting?: Record<string, any>
}

export const shortLinksLogic = kea<shortLinksLogicType>([
    path(['scenes', 'short-links', 'shortLinksLogic']),
    actions({
        setNewLinkDestinationUrl: (url: string) => ({ url }),
        setNewLinkExpirationDate: (date: string | null) => ({ date }),
        setNewLinkCustomKey: (customKey: string) => ({ customKey }),
        setNewLinkTags: (tags: string[]) => ({ tags }),
        setNewLinkComments: (comments: string) => ({ comments }),
        setNewLinkFolder: (folder: string) => ({ folder }),
        setNewLinkPassword: (password: string) => ({ password }),
        setNewLinkOgTitle: (title: string) => ({ title }),
        setNewLinkOgDescription: (description: string) => ({ description }),
        setNewLinkOgImage: (image: File | string | null) => ({ image }),
        setNewLinkUtmParams: (params: Record<string, string>) => ({ params }),
        setNewLinkTargeting: (targeting: Record<string, any>) => ({ targeting }),
        createShortLink: true,
        deleteShortLink: (key: string) => ({ key }),
        setEditingLink: (link: ShortLink | null) => ({ link }),
        updateShortLink: (key: string, changes: Partial<ShortLink>) => ({ key, changes }),
        setActiveTab: (tab: string) => ({ tab }),
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
            { 
                destination_url: '', 
                expiration_date: undefined,
                custom_key: '',
                tags: [],
                comments: '',
                folder: 'Links',
                password: '',
                og_title: '',
                og_description: '',
                og_image: null as (File | string | null),
                utm_params: {},
                targeting: {},
            } as NewShortLink,
            {
                setNewLinkDestinationUrl: (state, { url }) => ({ ...state, destination_url: url }),
                setNewLinkExpirationDate: (state, { date }) => ({ ...state, expiration_date: date || undefined }),
                setNewLinkCustomKey: (state, { customKey }) => ({ ...state, custom_key: customKey }),
                setNewLinkTags: (state, { tags }) => ({ ...state, tags }),
                setNewLinkComments: (state, { comments }) => ({ ...state, comments }),
                setNewLinkFolder: (state, { folder }) => ({ ...state, folder }),
                setNewLinkPassword: (state, { password }) => ({ ...state, password }),
                setNewLinkOgTitle: (state, { title }) => ({ ...state, og_title: title }),
                setNewLinkOgDescription: (state, { description }) => ({ ...state, og_description: description }),
                setNewLinkOgImage: (state, { image }) => ({ ...state, og_image: image }),
                setNewLinkUtmParams: (state, { params }) => ({ ...state, utm_params: params }),
                setNewLinkTargeting: (state, { targeting }) => ({ ...state, targeting }),
                createShortLink: () => ({ 
                    destination_url: '', 
                    expiration_date: undefined,
                    custom_key: '',
                    tags: [],
                    comments: '',
                    folder: 'Links',
                    password: '',
                    og_title: '',
                    og_description: '',
                    og_image: null as (File | string | null),
                    utm_params: {},
                    targeting: {},
                }),
            },
        ],
        editingLink: [
            null as ShortLink | null,
            {
                setEditingLink: (_, { link }) => link,
            },
        ],
        activeTab: [
            'links' as string,
            {
                setActiveTab: (_, { tab }) => tab,
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
            
            if (values.newLink.og_image instanceof File) {
                const formData = new FormData()
                Object.entries(values.newLink).forEach(([key, value]) => {
                    if (key === 'og_image' && value instanceof File) {
                        formData.append('og_image', value)
                    } else if (key === 'tags' && Array.isArray(value)) {
                        value.forEach(tag => formData.append('tags', tag))
                    } else if (value !== undefined && value !== null) {
                        if (typeof value === 'object') {
                            formData.append(key, JSON.stringify(value))
                        } else {
                            formData.append(key, value.toString())
                        }
                    }
                })
                
                await api.create('api/short_links/', formData)
            } else {
                await api.create('api/short_links/', values.newLink)
            }
            
            actions.loadShortLinks()
        },
        deleteShortLink: async ({ key }) => {
            await api.delete(`api/short_links/${key}`)
            actions.loadShortLinks()
        },
        updateShortLink: async ({ key, changes }) => {
            if (changes.og_image instanceof File) {
                const formData = new FormData()
                Object.entries(changes).forEach(([changeKey, value]) => {
                    if (changeKey === 'og_image' && value instanceof File) {
                        formData.append('og_image', value)
                    } else if (changeKey === 'tags' && Array.isArray(value)) {
                        value.forEach(tag => formData.append('tags', tag))
                    } else if (value !== undefined && value !== null) {
                        if (typeof value === 'object') {
                            formData.append(changeKey, JSON.stringify(value))
                        } else {
                            formData.append(changeKey, value.toString())
                        }
                    }
                })
                
                await api.update(`api/short_links/${key}`, formData)
            } else {
                await api.update(`api/short_links/${key}`, changes)
            }
            
            actions.loadShortLinks()
            actions.setEditingLink(null)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadShortLinks()
    }),
])
