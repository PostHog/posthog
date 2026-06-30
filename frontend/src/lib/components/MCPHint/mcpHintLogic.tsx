import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { toast } from 'react-toastify'

import { IconX } from '@posthog/icons'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

import type { mcpHintLogicType } from './mcpHintLogicType'
import { MCPHintToast } from './MCPHintToast'
import type { SurfaceKey } from './prompts'

// In production the toast auto-dismisses after a few seconds so it doesn't linger;
// in development we keep it open so it's easier to inspect.
const AUTO_DISMISS_MS = process.env.NODE_ENV === 'development' ? false : 15000

// A full week between hints, regardless of surface — these are promotional,
// so we err heavily on the side of not overloading people.
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000

export interface TryShowMCPHintOptions {
    /**
     * Replaces the generic per-surface toast prompt with one derived from the action the user just took
     * (e.g. the actual feature flag they created). Plain string; quoting is handled by the toast component.
     */
    derivedPrompt?: string
}

export function tryShowMCPHint(surfaceKey: SurfaceKey, options: TryShowMCPHintOptions = {}): void {
    try {
        const mounted = mcpHintLogic.findMounted()
        mounted?.actions.tryShowHint(surfaceKey, options.derivedPrompt)
    } catch (error) {
        console.warn('[mcpHint] dispatch failed; host listener will continue', { surfaceKey, error })
    }
}

export const mcpHintLogic = kea<mcpHintLogicType>([
    path(['lib', 'components', 'MCPHint', 'mcpHintLogic']),
    connect(() => ({
        values: [userLogic, ['user'], featureFlagLogic, ['featureFlags']],
        actions: [userLogic, ['updateUser'], eventUsageLogic, ['reportMCPHintShown', 'reportMCPHintDismissed']],
    })),
    actions({
        tryShowHint: (surfaceKey: SurfaceKey, derivedPrompt?: string) => ({ surfaceKey, derivedPrompt }),
        recordShown: (now: number) => ({ now }),
        dismissSurface: (surfaceKey: SurfaceKey) => ({ surfaceKey }),
        dismissAll: true,
        reenable: true,
    }),
    reducers({
        lastShownAt: [
            null as number | null,
            { persist: true },
            {
                recordShown: (_, { now }) => now,
                reenable: () => null,
            },
        ],
        dismissedSurfaces: [
            {} as Record<string, true>,
            { persist: true },
            {
                dismissSurface: (state, { surfaceKey }) => ({ ...state, [surfaceKey]: true }),
                reenable: () => ({}),
            },
        ],
        localGlobalOptOut: [
            false,
            { persist: true },
            {
                dismissAll: () => true,
                reenable: () => false,
            },
        ],
    }),
    loaders({
        topEvents: [
            [] as string[],
            {
                // Used to weave the team's real event names into the SQL editor's example prompts.
                // One-shot per logic mount; if the call fails we silently fall back to default examples.
                loadTopEvents: async () => {
                    try {
                        // Over-fetch: `buildSqlExamplesFromEvents` drops PostHog-internal (`$`-prefixed)
                        // events, so a team whose most-recent events are mostly internal could otherwise
                        // be left with nothing to surface.
                        const response = await api.eventDefinitions.list({
                            limit: 30,
                            ordering: '-last_seen_at',
                        })
                        const names = (response.results ?? []).map((d) => d.name).filter((n): n is string => Boolean(n))
                        return names
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),
    selectors({
        effectiveOptOut: [
            (s) => [s.localGlobalOptOut, s.user],
            (localOptOut: boolean, user: UserType | null): boolean => Boolean(localOptOut || user?.hide_mcp_hints),
        ],
        userRole: [(s) => [s.user], (user: UserType | null): string | null => user?.role_at_organization ?? null],
    }),
    listeners(({ values, actions }) => ({
        tryShowHint: ({ surfaceKey, derivedPrompt }) => {
            const now = Date.now()
            const sinceLast = values.lastShownAt ? now - values.lastShownAt : Infinity
            const cooldownActive = values.lastShownAt !== null && sinceLast < COOLDOWN_MS

            if (values.effectiveOptOut || Boolean(values.dismissedSurfaces[surfaceKey]) || cooldownActive) {
                return
            }

            try {
                toast.info(<MCPHintToast surfaceKey={surfaceKey} derivedPrompt={derivedPrompt} />, {
                    toastId: `mcp-hint-${surfaceKey}-${now}`,
                    autoClose: AUTO_DISMISS_MS,
                    closeOnClick: false,
                    draggable: false,
                    hideProgressBar: true,
                    icon: false,
                    // Clicking the X is the only way to permanently hide this surface — auto-dismiss
                    // (timeout) shouldn't count, so we wire dismissSurface here, not in onClose.
                    closeButton: ({ closeToast }) => (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconX />}
                            onClick={(e) => {
                                actions.dismissSurface(surfaceKey)
                                closeToast(e)
                            }}
                            data-attr="mcp-hint-close"
                        />
                    ),
                })
                actions.recordShown(now)
                actions.reportMCPHintShown(surfaceKey)
            } catch (error) {
                console.warn('[mcpHint] toast render failed', { surfaceKey, error })
            }
        },
        dismissSurface: ({ surfaceKey }) => {
            actions.reportMCPHintDismissed('surface', surfaceKey)
        },
        dismissAll: () => {
            toast.dismiss()
            actions.updateUser({ hide_mcp_hints: true })
            actions.reportMCPHintDismissed('all')
        },
        reenable: () => {
            actions.updateUser({ hide_mcp_hints: false })
        },
    })),
])
