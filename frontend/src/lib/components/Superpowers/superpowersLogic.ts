import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
// eslint-disable-next-line import/no-cycle
import { userLogic } from 'scenes/userLogic'

import type { superpowersLogicType } from './superpowersLogicType'

export type FakeStatusOverride = 'none' | 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'
export type FakeBillingAlert = 'none' | 'info' | 'warning' | 'error'

export const superpowersLogic = kea<superpowersLogicType>([
    path(['lib', 'components', 'Superpowers', 'superpowersLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            preflightLogic,
            ['preflight'],
            mcpHintLogic,
            ['dismissedSurfaces', 'effectiveOptOut'],
        ],
        actions: [mcpHintLogic, ['reenable as reenableMCPHints']],
    })),
    actions({
        openSuperpowers: true,
        closeSuperpowers: true,
        setFakeStatusOverride: (status: FakeStatusOverride) => ({ status }),
        setFakeBillingAlert: (alert: FakeBillingAlert) => ({ alert }),
    }),
    reducers({
        isSuperpowersOpen: [
            false,
            {
                openSuperpowers: () => true,
                closeSuperpowers: () => false,
            },
        ],
        fakeStatusOverride: [
            'none' as FakeStatusOverride,
            {
                setFakeStatusOverride: (_, { status }) => status,
            },
        ],
        fakeBillingAlert: [
            'none' as FakeBillingAlert,
            {
                setFakeBillingAlert: (_, { alert }) => alert,
            },
        ],
    }),
    selectors({
        superpowersEnabled: [
            (s) => [s.user, s.preflight],
            (user, preflight) => {
                return user?.is_staff || preflight?.is_debug || preflight?.instance_preferences?.debug_queries
            },
        ],
        mcpHintsDismissed: [
            (s) => [s.dismissedSurfaces, s.effectiveOptOut],
            (dismissedSurfaces: Record<string, true>, effectiveOptOut: boolean): boolean =>
                effectiveOptOut || Object.keys(dismissedSurfaces).length > 0,
        ],
    }),
])
