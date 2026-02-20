import { actions, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { windowValues } from 'kea-window-values'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SidePanelTab } from '~/types'

import type { sidePanelStateLogicType } from './sidePanelStateLogicType'

// The side panel imports a lot of other components so this allows us to avoid circular dependencies

/**
 * @deprecated Sidepanel is soft-deprecated as only notebooks will be kept in sidepanel in future releases.
 */
export const sidePanelStateLogic = kea<sidePanelStateLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelStateLogic']),
    actions({
        openSidePanel: (tab: SidePanelTab, options?: string) => ({ tab, options }),
        closeSidePanel: (tab?: SidePanelTab) => ({ tab }),
        setSidePanelOpen: (open: boolean) => ({ open }),
        setSidePanelOptions: (options: string | null) => ({ options }),
        setSidePanelAvailable: (available: boolean) => ({ available }),
        onSceneTabChanged: (previousTabId: string | null, newTabId: string) => ({ previousTabId, newTabId }),
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
    listeners(({ actions, values, cache }) => ({
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
        onSceneTabChanged: ({ previousTabId, newTabId }) => {
            const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
            if (!featureFlags?.[FEATURE_FLAGS.UX_REMOVE_SIDEPANEL]) {
                return
            }

            // Skip if we already processed this exact transition (activateTab fires early, setScene fires later)
            const transitionKey = `${previousTabId}->${newTabId}`
            if (cache.lastProcessedTransition === transitionKey) {
                return
            }
            cache.lastProcessedTransition = transitionKey

            if (!cache.sidePanelStateByTab) {
                cache.sidePanelStateByTab = {}
            }

            // Save current side panel state for the previous tab
            if (previousTabId) {
                cache.sidePanelStateByTab[previousTabId] = {
                    open: values.sidePanelOpen,
                    selectedTab: values.selectedTab,
                    selectedTabOptions: values.selectedTabOptions,
                }
            }

            // Restore state for the new tab (preserve current state for never-visited tabs
            // so the URL hash handler can set it if needed)
            const savedState = cache.sidePanelStateByTab[newTabId]
            if (savedState) {
                if (savedState.open && savedState.selectedTab) {
                    actions.openSidePanel(savedState.selectedTab, savedState.selectedTabOptions ?? undefined)
                } else {
                    actions.closeSidePanel()
                }
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
