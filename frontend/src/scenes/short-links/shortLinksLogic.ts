import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { shortLinksLogicType } from './shortLinksLogicType'
import { forms } from 'kea-forms'

export const shortLinksLogic = kea<shortLinksLogicType>([
    path(['scenes', 'short-links', 'shortLinksLogic']),

    loaders(() => ({
        shortLinks: {
            loadShortLinks: async () => {
                const response = await api.get('api/short_links/')
                return response.results
            },
        },
    })),

    forms(({ actions }) => ({
        link: {
            defaults: {
                id: '',
                origin_domain: 'phog.gg',
                origin_key: '',
                destination: '',
                description: '',
                tags: '',
                comments: '',
            },

            errors: ({ destination }) => ({
                destination: !destination ? 'Must have a destination url' : undefined,
            }),

            submit: async ({ id, ...link }, breakpoint) => {
                const updatedLink = id
                    ? await api.update(`api/short_links/${id}`, link)
                    : await api.create(`api/short_links`, link)
                breakpoint()

                actions.resetLink(updatedLink)

                console.log('link saved')
            },

            options: {
                showErrorsOnTouch: true,
                alwaysShowErrors: false,
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadShortLinks()
    }),
])
