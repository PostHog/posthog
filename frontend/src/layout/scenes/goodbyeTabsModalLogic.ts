import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'

import type { goodbyeTabsModalLogicType } from './goodbyeTabsModalLogicType'

const DISMISSED_KEY = 'posthog-tabs-farewell-dismissed'
const TAB_STATE_KEY = 'scene-tabs-state'
const PINNED_TAB_STATE_KEY = 'scene-tabs-pinned-state'

const getStorageKey = (key: string): string => {
    const teamId = getCurrentTeamIdOrNone() ?? 'null'
    return `${key}-${teamId}`
}

export interface FarewellTab {
    url: string
    title: string
    pinned: boolean
}

interface RawTab {
    pathname?: string
    search?: string
    hash?: string
    title?: string
    customTitle?: string | null
    pinned?: boolean
}

interface BackendResponse {
    tabs?: RawTab[]
    homepage?: RawTab | null
}

const safeParse = <T>(raw: string | null): T | null => {
    if (!raw) {
        return null
    }
    try {
        return JSON.parse(raw) as T
    } catch {
        return null
    }
}

const toFarewellTab = (raw: RawTab, pinned: boolean): FarewellTab | null => {
    const pathname = raw.pathname?.trim()
    if (!pathname) {
        return null
    }
    const url = `${pathname}${raw.search ?? ''}${raw.hash ?? ''}`
    const title = (raw.customTitle || raw.title || pathname).trim()
    return { url, title, pinned }
}

const collectLocal = (): FarewellTab[] => {
    const session = safeParse<RawTab[]>(sessionStorage.getItem(getStorageKey(TAB_STATE_KEY))) ?? []
    const pinnedRaw = safeParse<{ tabs?: RawTab[]; homepage?: RawTab | null } | RawTab[]>(
        localStorage.getItem(getStorageKey(PINNED_TAB_STATE_KEY))
    )

    let pinnedTabs: RawTab[] = []
    let homepage: RawTab | null = null
    if (Array.isArray(pinnedRaw)) {
        pinnedTabs = pinnedRaw
    } else if (pinnedRaw && typeof pinnedRaw === 'object') {
        pinnedTabs = Array.isArray(pinnedRaw.tabs) ? pinnedRaw.tabs : []
        homepage = pinnedRaw.homepage ?? null
    }

    const out: FarewellTab[] = []
    if (homepage) {
        const f = toFarewellTab(homepage, true)
        if (f) {
            out.push(f)
        }
    }
    for (const t of pinnedTabs) {
        const f = toFarewellTab(t, true)
        if (f) {
            out.push(f)
        }
    }
    for (const t of session) {
        const f = toFarewellTab(t, !!t.pinned)
        if (f) {
            out.push(f)
        }
    }
    return out
}

const dedupe = (tabs: FarewellTab[]): FarewellTab[] => {
    const seen = new Set<string>()
    const out: FarewellTab[] = []
    for (const tab of tabs) {
        if (seen.has(tab.url)) {
            continue
        }
        seen.add(tab.url)
        out.push(tab)
    }
    return out
}

const sortPinnedFirst = (tabs: FarewellTab[]): FarewellTab[] => {
    const pinned = tabs.filter((t) => t.pinned)
    const rest = tabs.filter((t) => !t.pinned)
    return [...pinned, ...rest]
}

export const goodbyeTabsModalLogic = kea<goodbyeTabsModalLogicType>([
    path(['layout', 'scenes', 'goodbyeTabsModalLogic']),
    actions({
        dismiss: true,
        open: true,
    }),
    reducers({
        dismissed: [
            false,
            { persist: true, storageKey: DISMISSED_KEY },
            {
                dismiss: () => true,
            },
        ],
        isOpen: [
            false,
            {
                open: () => true,
                dismiss: () => false,
            },
        ],
    }),
    loaders({
        backendTabs: [
            [] as FarewellTab[],
            {
                loadBackendTabs: async () => {
                    try {
                        const response = await api.get<BackendResponse>('api/user_home_settings/@me/')
                        const out: FarewellTab[] = []
                        if (response?.homepage) {
                            const f = toFarewellTab(response.homepage, true)
                            if (f) {
                                out.push(f)
                            }
                        }
                        for (const t of response?.tabs ?? []) {
                            const f = toFarewellTab(t, true)
                            if (f) {
                                out.push(f)
                            }
                        }
                        return out
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),
    reducers({
        localTabs: [
            [] as FarewellTab[],
            {
                open: () => collectLocal(),
            },
        ],
    }),
    selectors({
        tabs: [
            (s) => [s.backendTabs, s.localTabs],
            (backendTabs, localTabs): FarewellTab[] => sortPinnedFirst(dedupe([...backendTabs, ...localTabs])),
        ],
    }),
    listeners(({ actions }) => ({
        dismiss: () => {
            try {
                localStorage.removeItem(getStorageKey(PINNED_TAB_STATE_KEY))
                sessionStorage.removeItem(getStorageKey(TAB_STATE_KEY))
            } catch {
                // ignore
            }
        },
        open: () => {
            actions.loadBackendTabs()
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.dismissed) {
            return
        }
        const local = collectLocal()
        if (local.length > 0) {
            actions.open()
            return
        }
        // Backend may still have pins from another browser; fetch lazily.
        ;(async () => {
            try {
                const response = await api.get<BackendResponse>('api/user_home_settings/@me/')
                const hasAny = (response?.tabs?.length ?? 0) > 0 || !!response?.homepage
                if (hasAny) {
                    actions.open()
                }
            } catch {
                // ignore
            }
        })()
    }),
])
