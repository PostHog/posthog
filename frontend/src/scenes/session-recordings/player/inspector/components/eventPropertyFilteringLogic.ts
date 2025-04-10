import { connect, kea, path, selectors } from 'kea'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import { PROPERTY_KEYS } from '~/taxonomy/taxonomy'

import type { eventPropertyFilteringLogicType } from './eventPropertyFilteringLogicType'

export const eventPropertyFilteringLogic = kea<eventPropertyFilteringLogicType>([
    path(['scenes', 'session-recordings', 'player', 'inspector', 'components', 'eventPropertyFilteringLogic']),
    connect(() => ({
        values: [userPreferencesLogic, ['hidePostHogPropertiesInTable'], preflightLogic, ['isCloudOrDev']],
    })),
    selectors({
        filterProperties: [
            (s) => [s.hidePostHogPropertiesInTable, s.isCloudOrDev],
            (hidePostHogPropertiesInTable, isCloudOrDev) => {
                return (props: Record<string, any>) => {
                    if (!hidePostHogPropertiesInTable) {
                        return props
                    }

                    return Object.fromEntries(
                        Object.entries(props).filter(([key]) => {
                            const isPostHogProperty = key.startsWith('$') && PROPERTY_KEYS.includes(key)
                            const isNonDollarPostHogProperty =
                                isCloudOrDev && CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS.includes(key)
                            return !isPostHogProperty && !isNonDollarPostHogProperty
                        })
                    )
                }
            },
        ],
    }),
])
