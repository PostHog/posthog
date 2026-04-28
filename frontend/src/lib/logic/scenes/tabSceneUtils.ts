import { combineUrl, router } from 'kea-router'

import { sceneLogic } from 'scenes/sceneLogic'
import type { SceneTab } from 'scenes/sceneTypes'

export function getTabSceneParams(tabId: string): {
    searchParams: Record<string, any>
    hashParams: Record<string, any>
} {
    const tab = sceneLogic.findMounted()?.values.tabs.find((tab) => tab.id === tabId)

    return {
        searchParams: tab?.sceneParams?.searchParams ?? router.values.searchParams,
        hashParams: tab?.sceneParams?.hashParams ?? router.values.hashParams,
    }
}

export function updateTabUrl(
    tabId: string,
    pathname: string,
    searchParams: Record<string, any>,
    hashParams: Record<string, any>
): void {
    if (!sceneLogic.isMounted()) {
        router.actions.replace(pathname, searchParams, hashParams)
        return
    }

    if (sceneLogic.values.activeTabId === tabId) {
        router.actions.replace(pathname, searchParams, hashParams)
        return
    }

    const nextLocation = combineUrl(pathname, searchParams, hashParams)
    sceneLogic.actions.setTabs(
        sceneLogic.values.tabs.map(
            (tab): SceneTab =>
                tab.id === tabId
                    ? {
                          ...tab,
                          pathname: nextLocation.pathname,
                          search: nextLocation.search,
                          hash: nextLocation.hash,
                          sceneParams: {
                              ...tab.sceneParams,
                              params: tab.sceneParams?.params ?? {},
                              searchParams,
                              hashParams,
                          },
                      }
                    : tab
        )
    )
}
