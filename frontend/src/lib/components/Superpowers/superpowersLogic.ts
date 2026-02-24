import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import type { superpowersLogicType } from './superpowersLogicType'

export type FakeStatusOverride = 'none' | 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'

export const superpowersLogic = kea<superpowersLogicType>([
    path(['lib', 'components', 'Superpowers', 'superpowersLogic']),
    connect(() => ({
        values: [userLogic, ['user'], preflightLogic, ['preflight']],
    })),
    actions({
        openSuperpowers: true,
        closeSuperpowers: true,
        setFakeStatusOverride: (status: FakeStatusOverride) => ({ status }),
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
    }),
    selectors({
        superpowersEnabled: [
            (s) => [s.user, s.preflight],
            (user, preflight) => {
                return (
                    user?.is_staff ||
                    user?.is_impersonated ||
                    preflight?.is_debug ||
                    preflight?.instance_preferences?.debug_queries
                )
            },
        ],
    }),
])
