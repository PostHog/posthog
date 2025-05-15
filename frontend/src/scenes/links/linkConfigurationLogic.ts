import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { forms } from 'kea-forms'

import { UserBasicType } from '~/types'

export interface LinkType {
    id: string
    destination: string
    created_at?: string
    created_by?: UserBasicType
    origin_domain?: string
    origin_key?: string
    custom_key?: string
    tags?: string
    description?: string
    comments?: string
    folder?: string
    expiration_date?: string
    password?: string
    og_title?: string
    og_description?: string
    og_image?: string | File
    utm_params?: Record<string, string>
    targeting?: Record<string, any>
}

export interface Props {
    id: string
}

export const linkConfigurationLogic = kea([
    path((id) => ['scenes', 'links', 'linkConfigurationLogic', id]),
    props({} as Props),
    key(({ id }: Props) => id),
    loaders(() => ({
        link: [
            null as LinkType | null,
            {
                loadLink: async ({ id }: { id: string }) => {
                    return await api.get(`api/links/${id}`)
                },
            },
        ],
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
                const updatedLink = id ? await api.update(`api/links/${id}`, link) : await api.create(`api/links`, link)
                breakpoint()

                actions.resetLink(updatedLink)

                console.log('link saved')
            },

            options: {
                showErrorsOnTouch: true,
                alwaysShowErrors: false,
            },
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadLink({ id: props.id})
        }
    }),
])
