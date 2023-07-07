import { connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { SidebarCategory, BasicListItem } from '../types'
import Fuse from 'fuse.js'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from './utils'
import {
    AuthorizedUrlListType,
    KeyedAppUrl,
    authorizedUrlListLogic,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import type { toolbarSidebarLogicType } from './toolbarType'

const fuse = new Fuse<KeyedAppUrl>([], {
    keys: ['url'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const toolbarSidebarLogic = kea<toolbarSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'toolbarSidebarLogic']),
    connect(() => ({
        values: [
            authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['urlsKeyed', 'suggestionsLoading'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
        ],
        actions: [
            authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['addUrl', 'removeUrl', 'updateUrl'],
        ],
    })),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantUrls, s.suggestionsLoading],
            (relevantUrls, suggestionsLoading) => [
                {
                    key: 'sites',
                    title: 'Sites',
                    loading: suggestionsLoading,
                    items: relevantUrls.map(
                        ([url, matches]) =>
                            ({
                                key: url.url,
                                name: url.url,
                                url: url.type !== 'suggestion' ? urls.site(url.url) : null,
                                tag: url.type === 'suggestion' ? { status: 'warning', text: 'SUGGESTION' } : undefined,
                                searchMatch: matches
                                    ? {
                                          matchingFields: matches.map((match) => match.key),
                                          nameHighlightRanges: matches.find((match) => match.key === 'url')?.indices,
                                      }
                                    : null,
                                onRename:
                                    url.type !== 'suggestion'
                                        ? (newUrl) => actions.updateUrl(url.originalIndex, newUrl)
                                        : undefined,
                                menuItems:
                                    url.type !== 'suggestion'
                                        ? (initiateRename) => [
                                              {
                                                  items: [
                                                      {
                                                          to: urls.site(url.url),
                                                          targetBlank: true,
                                                          label: 'Open with Toolbar in new tab',
                                                      },
                                                  ],
                                              },
                                              {
                                                  items: [
                                                      {
                                                          onClick: initiateRename,
                                                          label: 'Edit',
                                                          keyboardShortcut: ['enter'],
                                                      },
                                                      {
                                                          onClick: () => actions.removeUrl(url.originalIndex),
                                                          status: 'danger',
                                                          label: 'Delete site',
                                                      },
                                                  ],
                                              },
                                          ]
                                        : [{ onClick: () => actions.addUrl(url.url), label: 'Apply suggestion' }],
                            } as BasicListItem)
                    ),
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.Site ? decodeURIComponent(sceneParams.params.url) : null
            },
        ],
        relevantUrls: [
            (s) => [s.urlsKeyed, navigation3000Logic.selectors.searchTerm],
            (urlsKeyed, searchTerm): [KeyedAppUrl, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return urlsKeyed.map((url) => [url, null])
            },
        ],
    })),
    subscriptions({
        urlsKeyed: (urlsKeyed) => {
            fuse.setCollection(urlsKeyed)
        },
    }),
])
