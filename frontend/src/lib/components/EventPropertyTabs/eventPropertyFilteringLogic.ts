import { connect, kea, selectors } from 'kea'
import type { eventPropertyFilteringLogicType } from 'scenes/session-recordings/player/inspector/components/eventPropertyFilteringLogicType'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS, PROPERTY_KEYS } from '~/taxonomy/taxonomy'

export const eventPropertyFilteringLogic = kea<eventPropertyFilteringLogicType>([
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
                            const isSystemProperty = props[key]?.system
                            return !isPostHogProperty && !isNonDollarPostHogProperty && !isSystemProperty
                        })
                    )
                }
            },
        ],
    }),
])
