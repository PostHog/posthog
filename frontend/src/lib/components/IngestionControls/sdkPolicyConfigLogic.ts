import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { AccessControlResourceType } from '~/types'

import type { sdkPolicyConfigLogicType } from './sdkPolicyConfigLogicType'
import { SDKPolicyConfig, Trigger, TriggerType } from './types'

export type IngestionControlsLogicProps = {
    logicKey: string
    resourceType: AccessControlResourceType | null
    matchType: 'any' | 'all'
    onChangeMatchType: (matchType: 'any' | 'all') => void
}

export const sdkPolicyConfigLogic = kea<sdkPolicyConfigLogicType>([
    path(['lib', 'components', 'IngestionControls', 'sdkPolicyConfigLogic']),
    actions({
        setMatchType: (matchType: SDKPolicyConfig['match_type']) => ({ matchType }),
        setSampleRate: (sampleRate: SDKPolicyConfig['sample_rate']) => ({ sampleRate }),
        setLinkedFeatureFlag: (linkedFeatureFlag: SDKPolicyConfig['linked_feature_flag']) => ({ linkedFeatureFlag }),
        setEventsTrigger: (eventsTrigger: SDKPolicyConfig['events_trigger']) => ({ eventsTrigger }),
        setUrlTrigger: (urlTrigger: SDKPolicyConfig['url_trigger']) => ({ urlTrigger }),
        setUrlBlocklist: (urlBlocklist: SDKPolicyConfig['url_blocklist']) => ({ urlBlocklist }),
        setMinimumDurationMilliseconds: (
            minimumDurationMilliseconds: SDKPolicyConfig['minimum_duration_milliseconds']
        ) => ({ minimumDurationMilliseconds }),
    }),
    reducers({
        matchType: [
            'all' as SDKPolicyConfig['match_type'],
            {
                setMatchType: (_, { matchType }) => matchType,
            },
        ],
        sampleRate: [
            1 as SDKPolicyConfig['sample_rate'],
            {
                setSampleRate: (_, { sampleRate }) => sampleRate,
            },
        ],
        minimumDurationMilliseconds: [
            null as SDKPolicyConfig['minimum_duration_milliseconds'],
            {
                setMinimumDurationMilliseconds: (_, { minimumDurationMilliseconds }) => minimumDurationMilliseconds,
            },
        ],
        linkedFeatureFlag: [
            null as SDKPolicyConfig['linked_feature_flag'],
            {
                setLinkedFeatureFlag: (_, { linkedFeatureFlag }) => linkedFeatureFlag,
            },
        ],
        eventsTrigger: [
            [] as SDKPolicyConfig['events_trigger'],
            {
                setEventsTrigger: (_, { eventsTrigger }) => eventsTrigger,
            },
        ],
        urlTrigger: [
            [] as SDKPolicyConfig['url_trigger'],
            {
                setUrlTrigger: (_, { urlTrigger }) => urlTrigger,
            },
        ],
        urlBlocklist: [
            [] as SDKPolicyConfig['url_blocklist'],
            {
                setUrlBlocklist: (_, { urlBlocklist }) => urlBlocklist,
            },
        ],
    }),
    loaders(({ values }) => ({
        policy: [
            null as SDKPolicyConfig | null,
            {
                loadPolicy: async () => {
                    return await api.errorTracking.sdkPolicyConfig.get()
                },
                savePolicy: async () => {
                    const newPolicy = {
                        match_type: values.matchType,
                        sample_rate: values.sampleRate,
                        minimum_duration_milliseconds: values.minimumDurationMilliseconds,
                        linked_feature_flag: values.linkedFeatureFlag,
                        events_trigger: values.eventsTrigger,
                        url_trigger: values.urlTrigger,
                        url_blocklist: values.urlBlocklist,
                    }
                    await api.errorTracking.sdkPolicyConfig.update(newPolicy)
                    return newPolicy
                },
            },
        ],
    })),
    selectors({
        triggers: [
            (s) => [
                s.sampleRate,
                s.minimumDurationMilliseconds,
                s.linkedFeatureFlag,
                s.eventsTrigger,
                s.urlTrigger,
                s.urlBlocklist,
            ],
            (
                sampleRate,
                minimumDurationMilliseconds,
                linkedFeatureFlag,
                eventsTrigger,
                urlTrigger,
                urlBlocklist
            ): Trigger[] => [
                {
                    type: TriggerType.URL_MATCH,
                    enabled: urlTrigger.length > 0,
                    urls: urlTrigger,
                },
                {
                    type: TriggerType.EVENT,
                    enabled: eventsTrigger.length > 0,
                    events: eventsTrigger,
                },
                {
                    type: TriggerType.FEATURE_FLAG,
                    enabled: !!linkedFeatureFlag,
                    key: linkedFeatureFlag?.key ?? null,
                },
                {
                    type: TriggerType.SAMPLING,
                    enabled: sampleRate < 1,
                    sampleRate: sampleRate,
                },
                {
                    type: TriggerType.MIN_DURATION,
                    enabled: !!minimumDurationMilliseconds && minimumDurationMilliseconds > 0,
                    minDurationMs: minimumDurationMilliseconds,
                },
                {
                    type: TriggerType.URL_BLOCKLIST,
                    enabled: urlBlocklist.length > 0,
                    urls: urlBlocklist,
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        loadPolicySuccess: ({ policy }) => {
            actions.setMatchType(policy.match_type)
            actions.setSampleRate(policy.sample_rate)
            actions.setMinimumDurationMilliseconds(policy.minimum_duration_milliseconds)
            actions.setLinkedFeatureFlag(policy.linked_feature_flag)
            actions.setEventsTrigger(policy.events_trigger)
            actions.setUrlTrigger(policy.url_trigger)
            actions.setUrlBlocklist(policy.url_blocklist)
        },
        setMatchType: () => actions.savePolicy(),
    })),
])
