import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { providersLogicType } from './providersLogicType'

export const providersLogic = kea<providersLogicType>([
    path(['scenes', 'messaging', 'providersLogic']),
    actions({
        editProvider: (id: string | null, template: string | null) => ({ id, template }),
    }),
    reducers({
        providerId: [null as string | null, { editProvider: (_, { id }) => id }],
        templateId: [null as string | null, { editProvider: (_, { template }) => template }],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.providerId, s.templateId],
            (providerId, templateId): Breadcrumb[] => {
                return [
                    {
                        key: Scene.MessagingBroadcasts,
                        name: 'Messaging',
                        path: urls.messagingBroadcasts(),
                    },
                    {
                        key: 'providers',
                        name: 'Providers',
                        path: urls.messagingProviders(),
                    },
                    ...(providerId === 'new' || templateId
                        ? [
                              {
                                  key: 'new-provider',
                                  name: 'New provider',
                                  path: urls.messagingProviderNew(),
                              },
                          ]
                        : providerId
                        ? [
                              {
                                  key: 'edit-provider',
                                  name: 'Edit provider',
                                  path: urls.messagingProvider(providerId),
                              },
                          ]
                        : []),
                ]
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/messaging/providers/new': () => {
            actions.editProvider('new', null)
        },
        '/messaging/providers/new/:template': ({ template }) => {
            actions.editProvider('new', template ?? null)
        },
        '/messaging/providers/:id': ({ id }) => {
            actions.editProvider(id ?? null, null)
        },
        '/messaging/providers': () => {
            actions.editProvider(null, null)
        },
    })),
])
