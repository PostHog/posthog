import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { UserBasicType } from '~/types'

import type { linkConfigurationLogicType } from './linkConfigurationLogicType'

export interface LinkType {
    id: string
    redirect_url: string
    short_link_domain: string
    short_code: string
    created_at?: string
    created_by?: UserBasicType
    description?: string
    updated_at?: string
}

export interface Props {
    id: string
}

export const linkConfigurationLogic = kea<linkConfigurationLogicType>([
    path((id) => ['scenes', 'links', 'linkConfigurationLogic', id]),
    props({} as Props),
    key(({ id }: Props) => id),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders({
        link: [
            null as LinkType | null,
            {
                loadLink: async ({ id }: { id: string }) => {
                    return await api.links.get(id)
                },
            },
        ],
    }),
    actions({
        deleteLink: (link: LinkType) => ({ link }),
    }),
    listeners(({ actions, values }) => ({
        deleteLink: async ({ link }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/links`,
                object: { name: link.short_link_domain + '/' + link.short_code, id: link.id },
                callback: (undo) => {
                    link.id && actions.deleteLink(link)
                    if (undo) {
                        refreshTreeItem('link', String(link.id))
                    } else {
                        deleteFromTree('link', String(link.id))
                    }
                    // Load latest change so a backwards navigation shows the link as deleted
                    actions.loadLink({ id: link.id })
                    router.actions.push(urls.links())
                },
            })
        },
    })),
    forms(({ actions }) => ({
        link: {
            defaults: {
                id: '',
                short_link_domain: 'phog.gg',
                short_code: '',
                redirect_url: '',
                description: '',
            } as LinkType,

            errors: ({ redirect_url }) => ({
                redirect_url: !redirect_url ? 'Must have a destination url' : undefined,
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
