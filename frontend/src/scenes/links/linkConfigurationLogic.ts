import { actions, afterMount, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { UserBasicType } from '~/types'

import type { linkConfigurationLogicType } from './linkConfigurationLogicType'

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

export const linkConfigurationLogic = kea<linkConfigurationLogicType>([
    path((id) => ['scenes', 'links', 'linkConfigurationLogic', id]),
    props({} as Props),
    key(({ id }: Props) => id),
    loaders(() => ({
        link: [
            null as LinkType | null,
            {
                loadLink: async ({ id }: { id: string }) => {
                    return await api.links.get(id)
                },
            },
        ],
    })),
    actions({
        deleteLink: (link: LinkType) => ({ link }),
    }),
    listeners(({ actions, values }) => ({
        deleteLink: async ({ link }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/links`,
                object: { name: link.origin_domain + '/' + link.origin_key, id: link.id },
                callback: (undo) => {
                    link.id && actions.deleteLink(link)
                    if (undo) {
                        refreshTreeItem('link', String(link.id))
                    } else {
                        deleteFromTree('link', String(link.id))
                    }
                    // Load latest change so a backwards navigation shows the flag as deleted
                    actions.loadLink()
                    router.actions.push(urls.links())
                },
            })
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
            },

            errors: ({ destination }) => ({
                destination: !destination ? 'Must have a destination url' : undefined,
            }),

            submit: async ({ id, ...link }, breakpoint) => {
                const updatedLink = id ? await api.links.update(id, link) : await api.links.create(link)
                breakpoint()

                actions.resetLink(updatedLink)

                router.actions.replace(urls.link(updatedLink.id))
            },

            options: {
                showErrorsOnTouch: true,
                alwaysShowErrors: false,
            },
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadLink({ id: props.id })
        }
    }),
])
