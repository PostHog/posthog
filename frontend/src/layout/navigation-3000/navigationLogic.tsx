import {
    IconChat,
    IconCursorClick,
    IconDashboard,
    IconDatabase,
    IconDecisionTree,
    IconGraph,
    IconHome,
    IconLive,
    IconLogomark,
    IconNotebook,
    IconPeople,
    IconPieChart,
    IconPlusSmall,
    IconRewindPlay,
    IconRocket,
    IconServer,
    IconSparkles,
    IconTestTube,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { lemonToast, Spinner } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isNotNil } from 'lib/utils'
import React from 'react'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { ProductKey } from '~/types'

import { navigationLogic } from '../navigation/navigationLogic'
import type { navigation3000LogicType } from './navigationLogicType'
import { dashboardsSidebarLogic } from './sidebars/dashboards'
import { dataManagementSidebarLogic } from './sidebars/dataManagement'
import { experimentsSidebarLogic } from './sidebars/experiments'
import { featureFlagsSidebarLogic } from './sidebars/featureFlags'
import { insightsSidebarLogic } from './sidebars/insights'
import { personsAndGroupsSidebarLogic } from './sidebars/personsAndGroups'
import { BasicListItem, ExtendedListItem, NavbarItem, SidebarNavbarItem } from './types'

/** Multi-segment item keys are joined using this separator for easy comparisons. */
export const ITEM_KEY_PART_SEPARATOR = '::'

export type Navigation3000Mode = 'none' | 'minimal' | 'full'

const MINIMUM_SIDEBAR_WIDTH_PX: number = 192
const DEFAULT_SIDEBAR_WIDTH_PX: number = 288
const MAXIMUM_SIDEBAR_WIDTH_PX: number = 1024
const MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE: number = 50

export const navigation3000Logic = kea<navigation3000LogicType>([
    path(['layout', 'navigation-3000', 'navigationLogic']),
    props({} as { inputElement?: HTMLInputElement | null }),
    connect(() => ({
        values: [
            sceneLogic,
            ['sceneConfig'],
            navigationLogic,
            ['mobileLayout'],
            teamLogic,
            ['currentTeam', 'hasOnboardedAnyProduct'],
        ],
        actions: [navigationLogic, ['closeAccountPopover']],
    })),
    actions({
        hideSidebar: true,
        showSidebar: (newNavbarItemId?: string) => ({ newNavbarItemId }),
        toggleNavCollapsed: (override?: boolean) => ({ override }),
        showNavOnMobile: true,
        hideNavOnMobile: true,
        toggleSidebar: true,
        setSidebarWidth: (width: number) => ({ width }),
        setSidebarOverslide: (overslide: number) => ({ overslide }),
        syncSidebarWidthWithMouseMove: (delta: number) => ({ delta }),
        syncSidebarWidthWithViewport: true,
        beginResize: true,
        endResize: true,
        acknowledgeSidebarKeyboardShortcut: true,
        setIsSearchShown: (isSearchShown: boolean) => ({ isSearchShown }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        initiateNewItemInCategory: (category: string) => ({ category }),
        initiateNewItemInlineInCategory: (category: string) => ({ category }),
        cancelNewItem: true,
        saveNewItem: (itemName: string) => ({ itemName }),
        saveNewItemComplete: true,
        setLastFocusedItemIndex: (index: number) => ({ index }),
        setLastFocusedItemByKey: (key: string | number) => ({ key }), // A wrapper over setLastFocusedItemIndex
        focusNextItem: true,
        focusPreviousItem: true,
        toggleAccordion: (key: string) => ({ key }),
    }),
    reducers({
        isSidebarShown: [
            true,
            {
                persist: true,
            },
            {
                hideSidebar: () => false,
                showSidebar: () => true,
                toggleSidebar: (isSidebarShown) => !isSidebarShown,
            },
        ],
        sidebarWidth: [
            DEFAULT_SIDEBAR_WIDTH_PX,
            { persist: true },
            {
                setSidebarWidth: (_, { width }) => width,
            },
        ],
        sidebarOverslide: [
            // Overslide is how far beyond the min/max sidebar width the cursor has moved
            0,
            {
                setSidebarOverslide: (_, { overslide }) => overslide,
            },
        ],
        isResizeInProgress: [
            false,
            {
                beginResize: () => true,
                endResize: () => false,
            },
        ],
        isNavCollapsedDesktop: [
            false,
            { persist: true },
            {
                toggleNavCollapsed: (state, { override }) => override ?? !state,
            },
        ],
        isNavShownMobile: [
            false,
            { persist: true },
            {
                showNavOnMobile: () => true,
                hideNavOnMobile: () => false,
                closeAccountPopover: () => false,
            },
        ],
        isSidebarKeyboardShortcutAcknowledged: [
            false,
            {
                persist: true,
            },
            {
                acknowledgeSidebarKeyboardShortcut: () => true,
            },
        ],
        activeNavbarItemIdRaw: [
            Scene.Dashboards as string,
            {
                persist: true,
            },
            {
                showSidebar: (state, { newNavbarItemId }) => newNavbarItemId || state,
            },
        ],
        isSearchShown: [
            false,
            {
                setIsSearchShown: (_, { isSearchShown }) => isSearchShown,
            },
        ],
        internalSearchTerm: [
            // Do not reference this outside of this file
            // `searchTerm` is the outwards-facing value, as it's made empty when search is hidden
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        lastFocusedItemIndex: [
            -1 as number,
            {
                setLastFocusedItemIndex: (_, { index }) => index,
            },
        ],
        accordionCollapseMapping: [
            {} as Record<string, boolean>,
            {
                persist: true,
            },
            {
                toggleAccordion: (state, { key }) => ({
                    ...state,
                    [key]: !state[key],
                }),
            },
        ],
        newItemInlineCategory: [
            null as string | null,
            {
                initiateNewItemInlineInCategory: (_, { category }) => category,
                saveNewItemComplete: () => null,
                cancelNewItem: () => null,
                toggleSidebar: () => null,
                showSidebar: () => null,
                hideSidebar: () => null,
            },
        ],
        savingNewItem: [
            false,
            {
                saveNewItem: () => true,
                saveNewItemComplete: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        initiateNewItemInCategory: ({ category: categoryKey }) => {
            const category = values.activeNavbarItem?.logic.values.contents?.find((item) => item.key === categoryKey)
            if (!category) {
                throw new Error(`Sidebar category '${categoryKey}' doesn't exist`)
            } else if (!category.onAdd || typeof category.onAdd !== 'function') {
                throw new Error(`Sidebar category '${categoryKey}' doesn't support onAdd`)
            }
            if (category.onAdd.length === 0) {
                ;(category.onAdd as () => void)() // If a zero-arg function, call it immediately
            } else {
                actions.initiateNewItemInlineInCategory(categoryKey) // Otherwise initiate inline item creation
            }
        },
        saveNewItem: async ({ itemName }) => {
            try {
                const categoryKey = values.newItemInlineCategory
                if (!categoryKey) {
                    throw new Error(`Can't save new sidebar item without a category`)
                }
                const category = values.activeNavbarItem?.logic.values.contents?.find(
                    (item) => item.key === categoryKey
                )
                if (!category) {
                    throw new Error(`Sidebar category '${categoryKey}' doesn't exist`)
                } else if (!category.onAdd || typeof category.onAdd !== 'function') {
                    throw new Error(`Sidebar category '${categoryKey}' doesn't support onAdd`)
                }
                await category.onAdd(itemName)
            } catch (e) {
                captureException(e)
                console.error(e)
                lemonToast.error('Something went wrong while saving the item. Please try again.')
            } finally {
                actions.saveNewItemComplete()
            }
        },
        syncSidebarWidthWithMouseMove: ({ delta }) => {
            const newWidthRaw = values.sidebarWidth + values.sidebarOverslide + delta
            let newWidth = newWidthRaw
            if (newWidth < MINIMUM_SIDEBAR_WIDTH_PX) {
                newWidth = MINIMUM_SIDEBAR_WIDTH_PX
            } else if (newWidth > MAXIMUM_SIDEBAR_WIDTH_PX) {
                newWidth = MAXIMUM_SIDEBAR_WIDTH_PX
            }
            if (newWidth > window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)) {
                newWidth = window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)
            }
            actions.setSidebarWidth(newWidth)
            actions.setSidebarOverslide(newWidthRaw - newWidth)
            if (newWidthRaw < MINIMUM_SIDEBAR_WIDTH_PX / 2) {
                if (values.isSidebarShown) {
                    actions.hideSidebar()
                }
            } else {
                if (!values.isSidebarShown) {
                    actions.showSidebar()
                }
            }
        },
        syncSidebarWidthWithViewport: () => {
            if (values.sidebarWidth > window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100)) {
                // Clamp
                actions.setSidebarWidth(window.innerWidth * (MAXIMUM_SIDEBAR_WIDTH_PERCENTAGE / 100))
            }
        },
        endResize: () => {
            actions.setSidebarOverslide(values.isSidebarShown ? 0 : -MINIMUM_SIDEBAR_WIDTH_PX)
        },
        toggleSidebar: () => {
            actions.endResize()
        },
        focusNextItem: () => {
            const nextIndex = values.lastFocusedItemIndex + 1
            if (nextIndex < values.sidebarContentsFlattened.length) {
                actions.setLastFocusedItemIndex(nextIndex)
            }
        },
        focusPreviousItem: () => {
            const nextIndex = values.lastFocusedItemIndex - 1
            if (nextIndex >= -1) {
                actions.setLastFocusedItemIndex(nextIndex)
            }
        },
        setLastFocusedItemByKey: ({ key }) => {
            const index = values.sidebarContentsFlattened.findIndex((item) =>
                Array.isArray(item.key) ? item.key.includes(key as string) : item.key === key
            )
            if (index !== -1) {
                actions.setLastFocusedItemIndex(index)
            }
        },
    })),
    selectors({
        mode: [
            (s) => [s.sceneConfig],
            (sceneConfig): Navigation3000Mode => {
                return sceneConfig?.layout === 'plain' && !sceneConfig.allowUnauthenticated
                    ? 'minimal'
                    : sceneConfig?.layout !== 'plain'
                    ? 'full'
                    : 'none'
            },
        ],
        isNavShown: [
            (s) => [s.isNavShownMobile, s.mobileLayout],
            (isNavShownMobile, mobileLayout): boolean => !mobileLayout || isNavShownMobile,
        ],
        isNavCollapsed: [
            (s) => [s.isNavCollapsedDesktop, s.mobileLayout],
            (isNavCollapsedDesktop, mobileLayout): boolean => !mobileLayout && isNavCollapsedDesktop,
        ],
        navbarItems: [
            (s) => [
                featureFlagLogic.selectors.featureFlags,
                dashboardsModel.selectors.dashboardsLoading,
                dashboardsModel.selectors.pinnedDashboards,
                s.currentTeam,
                s.hasOnboardedAnyProduct,
            ],
            (
                featureFlags,
                dashboardsLoading,
                pinnedDashboards,
                currentTeam,
                hasOnboardedAnyProduct
            ): NavbarItem[][] => {
                const isUsingSidebar = featureFlags[FEATURE_FLAGS.POSTHOG_3000_NAV]
                const hasOnboardedFeatureFlags = currentTeam?.has_completed_onboarding_for?.[ProductKey.FEATURE_FLAGS]
                const sectionOne: NavbarItem[] = hasOnboardedAnyProduct
                    ? [
                          {
                              identifier: Scene.ProjectHomepage,
                              label: 'Home',
                              icon: <IconHome />,
                              to: urls.projectHomepage(),
                          },
                          featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]
                              ? {
                                    identifier: Scene.Max,
                                    label: 'Max AI',
                                    icon: <IconSparkles />,
                                    to: urls.max(),
                                }
                              : null,
                          {
                              identifier: Scene.Dashboards,
                              label: 'Dashboards',
                              icon: <IconDashboard />,
                              logic: isUsingSidebar ? dashboardsSidebarLogic : undefined,
                              to: isUsingSidebar ? undefined : urls.dashboards(),
                              sideAction: {
                                  identifier: 'pinned-dashboards-dropdown',
                                  dropdown: {
                                      overlay: (
                                          <LemonMenuOverlay
                                              items={[
                                                  {
                                                      title: 'Pinned dashboards',
                                                      items: pinnedDashboards.map((dashboard) => ({
                                                          label: dashboard.name,
                                                          to: urls.dashboard(dashboard.id),
                                                      })),
                                                      footer: dashboardsLoading && (
                                                          <div className="px-2 py-1 text-text-secondary-3000">
                                                              <Spinner /> Loading…
                                                          </div>
                                                      ),
                                                  },
                                              ]}
                                          />
                                      ),
                                      placement: 'bottom-end',
                                  },
                              },
                          },
                          {
                              identifier: Scene.Notebooks,
                              label: 'Notebooks',
                              icon: <IconNotebook />,
                              to: urls.notebooks(),
                          },
                          {
                              identifier: Scene.DataManagement,
                              label: 'Data management',
                              icon: <IconDatabase />,
                              logic: isUsingSidebar ? dataManagementSidebarLogic : undefined,
                              to: isUsingSidebar ? undefined : urls.eventDefinitions(),
                          },
                          {
                              identifier: Scene.PersonsManagement,
                              label: 'People and groups',
                              icon: <IconPeople />,
                              logic: isUsingSidebar ? personsAndGroupsSidebarLogic : undefined,
                              to: isUsingSidebar ? undefined : urls.persons(),
                          },
                          {
                              identifier: Scene.Activity,
                              label: 'Activity',
                              icon: <IconLive />,
                              to: featureFlags[FEATURE_FLAGS.LIVE_EVENTS] ? urls.activity() : urls.events(),
                          },
                      ]
                    : [
                          {
                              identifier: Scene.Products,
                              label: 'Welcome to PostHog',
                              icon: <IconLogomark />,
                              to: urls.products(),
                          },
                      ]

                return [
                    sectionOne,
                    [
                        {
                            identifier: Scene.SavedInsights,
                            label: 'Product analytics',
                            icon: <IconGraph />,
                            logic: isUsingSidebar ? insightsSidebarLogic : undefined,
                            to: isUsingSidebar ? undefined : urls.savedInsights(),
                            sideAction: {
                                icon: <IconPlusSmall />, // The regular plus is too big
                                to: urls.insightNew(),
                                tooltip: 'New insight',
                                identifier: Scene.Insight,
                            },
                        },
                        {
                            identifier: Scene.WebAnalytics,
                            label: 'Web analytics',
                            icon: <IconPieChart />,
                            to: isUsingSidebar ? undefined : urls.webAnalytics(),
                            tag: 'beta' as const,
                        },
                        {
                            identifier: Scene.Replay,
                            label: 'Session replay',
                            icon: <IconRewindPlay />,
                            to: urls.replay(),
                        },
                        featureFlags[FEATURE_FLAGS.ERROR_TRACKING]
                            ? {
                                  identifier: Scene.ErrorTracking,
                                  label: 'Error tracking',
                                  icon: <IconWarning />,
                                  to: urls.errorTracking(),
                                  tag: 'alpha' as const,
                              }
                            : null,
                        featureFlags[FEATURE_FLAGS.HEATMAPS_UI]
                            ? {
                                  identifier: Scene.Heatmaps,
                                  label: 'Heatmaps',
                                  icon: <IconCursorClick />,
                                  to: isUsingSidebar ? undefined : urls.heatmaps(),
                                  tag: 'alpha' as const,
                              }
                            : null,
                        {
                            identifier: Scene.FeatureFlags,
                            label: 'Feature flags',
                            icon: <IconToggle />,
                            logic: isUsingSidebar ? featureFlagsSidebarLogic : undefined,
                            to: isUsingSidebar ? undefined : urls.featureFlags(),
                        },
                        {
                            identifier: Scene.Experiments,
                            label: 'A/B testing',
                            icon: <IconTestTube />,
                            logic: isUsingSidebar ? experimentsSidebarLogic : undefined,
                            to: isUsingSidebar ? undefined : urls.experiments(),
                        },
                        {
                            identifier: Scene.Surveys,
                            label: 'Surveys',
                            icon: <IconChat />,
                            to: urls.surveys(),
                        },
                        featureFlags[FEATURE_FLAGS.PRODUCT_INTRO_PAGES] !== 'test' || hasOnboardedFeatureFlags
                            ? {
                                  identifier: Scene.EarlyAccessFeatures,
                                  label: 'Early access features',
                                  icon: <IconRocket />,
                                  to: urls.earlyAccessFeatures(),
                              }
                            : null,
                        {
                            identifier: Scene.DataWarehouse,
                            label: 'Data warehouse',
                            icon: <IconServer />,
                            to: isUsingSidebar ? undefined : urls.dataWarehouse(),
                        },
                        hasOnboardedAnyProduct
                            ? {
                                  identifier: Scene.Pipeline,
                                  label: 'Data pipeline',
                                  icon: <IconDecisionTree />,
                                  to: urls.pipeline(),
                              }
                            : null,
                    ].filter(isNotNil),
                ]
            },
        ],
        navbarItemIdMapping: [
            (s) => [s.navbarItems],
            (navbarItems): Record<string, NavbarItem> => {
                return Object.fromEntries(navbarItems.flat().map((item) => [item.identifier, item]))
            },
        ],
        sidebarOverslideDirection: [
            (s) => [s.sidebarOverslide],
            (sidebarOverslide): 'min' | 'max' | null => {
                if (sidebarOverslide < 0) {
                    return 'min'
                } else if (sidebarOverslide > 0) {
                    return 'max'
                }
                return null
            },
        ],
        activeNavbarItem: [
            (s) => [s.activeNavbarItemId, s.navbarItemIdMapping],
            (activeNavbarItemId, navbarItemIdMapping): SidebarNavbarItem | null => {
                const item = activeNavbarItemId ? navbarItemIdMapping[activeNavbarItemId] : null
                return item && 'logic' in item ? (item as SidebarNavbarItem) : null
            },
        ],
        searchTerm: [
            (s) => [s.internalSearchTerm, s.isSearchShown],
            (internalSearchTerm, isSearchShown): string => {
                return isSearchShown ? internalSearchTerm : ''
            },
        ],
        sidebarContentsFlattened: [
            (s) => [(state) => s.activeNavbarItem(state)?.logic?.findMounted()?.selectors.contents(state) || null],
            (sidebarContents): BasicListItem[] | ExtendedListItem[] =>
                sidebarContents ? sidebarContents.flatMap((item) => ('items' in item ? item.items : item)) : [],
        ],
        normalizedActiveListItemKey: [
            (s) => [
                (state) =>
                    s.activeNavbarItem(state)?.logic?.findMounted()?.selectors.activeListItemKey?.(state) || null,
            ],
            (activeListItemKey): string | number | string[] | null =>
                activeListItemKey
                    ? Array.isArray(activeListItemKey)
                        ? activeListItemKey.join(ITEM_KEY_PART_SEPARATOR)
                        : activeListItemKey
                    : null,
        ],
        activeNavbarItemId: [
            (s) => [s.activeNavbarItemIdRaw, featureFlagLogic.selectors.featureFlags],
            (activeNavbarItemIdRaw, featureFlags): string | null => {
                if (!featureFlags[FEATURE_FLAGS.POSTHOG_3000_NAV]) {
                    return null
                }
                return activeNavbarItemIdRaw
            },
        ],
        newItemCategory: [
            (s) => [
                (state) => s.activeNavbarItem(state)?.logic?.findMounted()?.selectors.contents(state) || null,
                s.newItemInlineCategory,
                router.selectors.location,
            ],
            (sidebarContents, newItemInlineCategory, location): string | null => {
                if (!sidebarContents) {
                    return null
                }
                if (newItemInlineCategory) {
                    return newItemInlineCategory
                }
                return (
                    sidebarContents.find(
                        (category) => typeof category.onAdd === 'string' && category.onAdd === location.pathname
                    )?.key || null
                )
            },
        ],
    }),
    subscriptions(({ props, cache, actions, values }) => ({
        isResizeInProgress: (isResizeInProgress) => {
            if (isResizeInProgress) {
                cache.onMouseMove = (e: MouseEvent): void => actions.syncSidebarWidthWithMouseMove(e.movementX)
                cache.onMouseUp = (e: MouseEvent): void => {
                    if (e.button === 0) {
                        actions.endResize()
                    }
                }
                document.addEventListener('mousemove', cache.onMouseMove)
                document.addEventListener('mouseup', cache.onMouseUp)
                return () => {}
            }
            document.removeEventListener('mousemove', cache.onMouseMove)
            document.removeEventListener('mouseup', cache.onMouseUp)
        },
        sidebarContentsFlattened: (sidebarContentsFlattened) => {
            for (const item of sidebarContentsFlattened) {
                if (!item.ref) {
                    item.ref = React.createRef() // Inject refs for keyboard navigation
                }
            }
            actions.setLastFocusedItemIndex(-1) // Reset focused item index on contents change
        },
        lastFocusedItemIndex: (lastFocusedItemIndex) => {
            if (lastFocusedItemIndex >= 0) {
                const item = values.sidebarContentsFlattened[lastFocusedItemIndex]
                item.ref?.current?.focus()
            } else {
                props.inputElement?.focus()
            }
        },
    })),
    events(({ props, actions, cache }) => ({
        afterMount: () => {
            cache.onResize = () => actions.syncSidebarWidthWithViewport()
            cache.onKeyDown = (e: KeyboardEvent) => {
                if (e.key === 'b' && (e.metaKey || e.ctrlKey)) {
                    actions.toggleSidebar()
                    e.preventDefault()
                }
                if (e.key === 'f' && e.shiftKey && (e.metaKey || e.ctrlKey)) {
                    actions.setIsSearchShown(true)
                    props.inputElement?.focus()
                    e.preventDefault()
                }
            }
            window.addEventListener('resize', cache.onResize)
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            window.removeEventListener('resize', cache.onResize)
            window.removeEventListener('resize', cache.onKeyDown)
        },
    })),
])
