import { connect, kea, path, selectors } from 'kea'
import { userPreferencesLogic } from 'lib/logic/userPreferencesLogic'
import { NON_DOLLAR_POSTHOG_PROPERTY_KEYS, PROPERTY_KEYS } from 'lib/taxonomy'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { eventPropertyFilteringLogicType } from './eventPropertyFilteringLogicType'

export const eventPropertyFilteringLogic = kea<eventPropertyFilteringLogicType>([
    path(['scenes', 'session-recordings', 'player', 'inspector', 'components', 'eventPropertyFilteringLogic']),
    connect({
        values: [userPreferencesLogic, ['hidePostHogPropertiesInTable'], preflightLogic, ['isCloudOrDev']],
    }),
    selectors({
        promoteProperties: [
            () => [],
            () => {
                return (event: string): string[] | undefined => {
                    if (['$pageview', '$pageleave'].includes(event)) {
                        return ['$current_url', '$title', '$referrer']
                    } else if (event === '$groupidentify') {
                        return ['$group_type', '$group_key', '$group_set']
                    } else if (event === '$screen') {
                        return ['$screen_name']
                    } else if (event === '$web_vitals') {
                        return [
                            '$web_vitals_FCP_value',
                            '$web_vitals_CLS_value',
                            '$web_vitals_INP_value',
                            '$web_vitals_LCP_value',
                            '$web_vitals_FCP_event',
                            '$web_vitals_CLS_event',
                            '$web_vitals_INP_event',
                            '$web_vitals_LCP_event',
                        ]
                    } else if (event === '$set') {
                        return ['$set', '$set_once']
                    }
                }
            },
        ],
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
                                isCloudOrDev && NON_DOLLAR_POSTHOG_PROPERTY_KEYS.includes(key)
                            return !isPostHogProperty && !isNonDollarPostHogProperty
                        })
                    )
                }
            },
        ],
    }),
])
