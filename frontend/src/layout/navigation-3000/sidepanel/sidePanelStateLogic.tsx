import { actions, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { windowValues } from 'kea-window-values'
import posthog from 'posthog-js'
import React from 'react'

import { SidePanelTab } from '~/types'

import type { sidePanelStateLogicType } from './sidePanelStateLogicType'

export const WithinSidePanelContext = React.createContext<boolean>(false)

// The side panel imports a lot of other components so this allows us to avoid circular dependencies

export const sidePanelStateLogic = kea<sidePanelStateLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStateLogic']),
    actions({
        openSidePanel: (tab: SidePanelTab, options?: string) => ({ tab, options }),
        closeSidePanel: (tab?: SidePanelTab) => ({ tab }),
        setSidePanelOpen: (open: boolean) => ({ open }),
        setSidePanelOptions: (options: string | null) => ({ options }),
        setSidePanelAvailable: (available: boolean) => ({ available }),
    }),

    reducers(() => ({
        sidePanelAvailable: [
            false,
            {
                setSidePanelAvailable: (_, { available }) => available,
            },
        ],
        selectedTab: [
            null as SidePanelTab | null,
            { persist: true },
            {
                openSidePanel: (_, { tab }) => tab,
            },
        ],

        selectedTabOptions: [
            null as string | null,
            {
                openSidePanel: (_, { options }) => options ?? null,
                setSidePanelOptions: (_, { options }) => options ?? null,
                closeSidePanel: () => null,
            },
        ],
        sidePanelOpen: [
            false,
            { persist: true },
            {
                setSidePanelOpen: (_, { open }) => open,
            },
        ],
    })),
    windowValues(() => ({
        modalMode: (window: Window) => window.innerWidth < 992, // Sync width threshold with Sass variable $lg!
    })),
    listeners(({ actions, values }) => ({
        // NOTE: We explicitly reference the actions instead of connecting so that people don't accidentally
        // use this logic instead of sidePanelStateLogic
        openSidePanel: ({ tab }) => {
            posthog.capture('sidebar opened', { tab })
            actions.setSidePanelOpen(true)
        },
        closeSidePanel: ({ tab }) => {
            posthog.capture('sidebar closed', { tab })
            if (!tab) {
                // If we aren't specifiying the tab we always close
                actions.setSidePanelOpen(false)
            } else if (values.selectedTab === tab) {
                // Otherwise we only close it if the tab is the currently open one
                actions.setSidePanelOpen(false)
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        '*': (_, _search, hashParams) => {
            if ('supportModal' in hashParams) {
                const [kind, area] = (hashParams['supportModal'] || '').split(':')

                delete hashParams['supportModal'] // legacy value
                hashParams['panel'] = `support:${kind ?? ''}:${area ?? ''}`
                router.actions.replace(router.values.location.pathname, router.values.searchParams, hashParams)
                return
            }

            const panelHash = hashParams['panel'] as string | undefined

            if (panelHash) {
                const [panel, ...panelOptions] = panelHash.split(':')

                if (
                    panel &&
                    (panel !== values.selectedTab ||
                        !values.sidePanelOpen ||
                        panelOptions.join(':') !== values.selectedTabOptions)
                ) {
                    actions.openSidePanel(panel as SidePanelTab, panelOptions.join(':'))
                }
            }
        },
    })),
    actionToUrl(({ values }) => {
        const updateUrl = (): any => {
            let panelHash: string = values.selectedTab ?? ''

            if (values.selectedTabOptions) {
                panelHash += `:${values.selectedTabOptions}`
            }
            return [
                router.values.location.pathname,
                router.values.searchParams,
                {
                    ...router.values.hashParams,
                    panel: panelHash,
                },
                { replace: true },
            ]
        }
        return {
            openSidePanel: () => updateUrl(),
            setSidePanelOptions: () => updateUrl(),
            closeSidePanel: () => {
                const hashParams = { ...router.values.hashParams }
                delete hashParams['panel']
                return [router.values.location.pathname, router.values.searchParams, hashParams, { replace: true }]
            },
        }
    }),
])
