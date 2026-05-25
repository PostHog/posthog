import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { toast } from 'react-toastify'

import { IconX } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

import type { mcpHintLogicType } from './mcpHintLogicType'
import { MCPHintToast } from './MCPHintToast'
import type { SurfaceKey, SurfacePromptContext } from './prompts'

// In production the toast auto-dismisses after a few seconds so it doesn't linger;
// in development we keep it open so it's easier to inspect.
const AUTO_DISMISS_MS = process.env.NODE_ENV === 'development' ? false : 15000

// A full week between hints, regardless of surface — these are promotional,
// so we err heavily on the side of not overloading people.
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000

export function tryShowMCPHint(surfaceKey: SurfaceKey, context?: SurfacePromptContext): void {
    try {
        const mounted = mcpHintLogic.findMounted()
        if (!mounted?.values.featureEnabled) {
            return
        }

        mounted.actions.tryShowHint(surfaceKey, context)
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
        tryShowHint: (surfaceKey: SurfaceKey, context?: SurfacePromptContext) => ({ surfaceKey, context }),
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
    selectors({
        featureEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: Record<string, boolean | string>): boolean =>
                featureFlags[FEATURE_FLAGS.MCP_HINTS] === 'test',
        ],
        effectiveOptOut: [
            (s) => [s.localGlobalOptOut, s.user],
            (localOptOut: boolean, user: UserType | null): boolean => Boolean(localOptOut || user?.hide_mcp_hints),
        ],
    }),
    listeners(({ values, actions }) => ({
        tryShowHint: ({ surfaceKey, context }) => {
            const now = Date.now()
            const sinceLast = values.lastShownAt ? now - values.lastShownAt : Infinity
            const cooldownActive = values.lastShownAt !== null && sinceLast < COOLDOWN_MS

            if (values.effectiveOptOut || Boolean(values.dismissedSurfaces[surfaceKey]) || cooldownActive) {
                return
            }

            try {
                toast.info(<MCPHintToast surfaceKey={surfaceKey} context={context} />, {
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
