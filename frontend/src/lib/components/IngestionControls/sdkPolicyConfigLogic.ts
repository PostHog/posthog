import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { sdkPolicyConfigLogicType } from './sdkPolicyConfigLogicType'
import { SDKPolicyConfig, SDKPolicyConfigContext, Trigger, TriggerType } from './types'

export type IngestionControlsLogicProps = {
    logicKey: SDKPolicyConfigContext
}

export const sdkPolicyConfigLogic = kea<sdkPolicyConfigLogicType>([
    props({} as IngestionControlsLogicProps),
    key(({ logicKey }) => logicKey),
    path((key) => ['lib', 'components', 'IngestionControls', 'sdkPolicyConfigLogic', key]),
    actions({
        setMatchType: (matchType: SDKPolicyConfig['match_type']) => ({ matchType }),
        setSampleRate: (sampleRate: SDKPolicyConfig['sample_rate']) => ({ sampleRate }),
        setLinkedFeatureFlag: (linkedFeatureFlag: SDKPolicyConfig['linked_feature_flag']) => ({ linkedFeatureFlag }),
        setEventTriggers: (eventTriggers: SDKPolicyConfig['event_triggers']) => ({ eventTriggers }),
        setUrlTriggers: (urlTriggers: SDKPolicyConfig['url_triggers']) => ({ urlTriggers }),
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
                loadPolicySuccess: (_, { policy }) => policy.match_type,
            },
        ],
        sampleRate: [
            1 as SDKPolicyConfig['sample_rate'],
            {
                setSampleRate: (_, { sampleRate }) => sampleRate,
                loadPolicySuccess: (_, { policy }) => policy.sample_rate,
            },
        ],
        minimumDurationMilliseconds: [
            null as SDKPolicyConfig['minimum_duration_milliseconds'],
            {
                setMinimumDurationMilliseconds: (_, { minimumDurationMilliseconds }) => minimumDurationMilliseconds,
                loadPolicySuccess: (_, { policy }) => policy.minimum_duration_milliseconds,
            },
        ],
        linkedFeatureFlag: [
            null as SDKPolicyConfig['linked_feature_flag'],
            {
                setLinkedFeatureFlag: (_, { linkedFeatureFlag }) => linkedFeatureFlag,
                loadPolicySuccess: (_, { policy }) => policy.linked_feature_flag,
            },
        ],
        eventTriggers: [
            [] as SDKPolicyConfig['event_triggers'],
            {
                setEventTriggers: (_, { eventTriggers }) => eventTriggers,
                loadPolicySuccess: (_, { policy }) => policy.event_triggers,
            },
        ],
        urlTriggers: [
            [] as SDKPolicyConfig['url_triggers'],
            {
                setUrlTriggers: (_, { urlTriggers }) => urlTriggers,
                loadPolicySuccess: (_, { policy }) => policy.url_triggers,
            },
        ],
        urlBlocklist: [
            [] as SDKPolicyConfig['url_blocklist'],
            {
                setUrlBlocklist: (_, { urlBlocklist }) => urlBlocklist,
                loadPolicySuccess: (_, { policy }) => policy.url_blocklist,
            },
        ],
    }),
    loaders(({ props: { logicKey }, values }) => ({
        policy: [
            null as SDKPolicyConfig | null,
            {
                loadPolicy: async () => {
                    const response = await api.errorTracking.sdkPolicyConfig.list(logicKey)
                    // TODO: right now we only allow for a single policy per context
                    // In future this should be extended to allow for per library policies
                    return response[0]
                },
                savePolicy: async () => {
                    if (values.policy) {
                        const newPolicy = {
                            id: values.policy.id,
                            match_type: values.matchType,
                            sample_rate: values.sampleRate,
                            minimum_duration_milliseconds: values.minimumDurationMilliseconds,
                            linked_feature_flag: values.linkedFeatureFlag,
                            event_triggers: values.eventTriggers,
                            url_triggers: values.urlTriggers,
                            url_blocklist: values.urlBlocklist,
                        }
                        await api.errorTracking.sdkPolicyConfig.update(newPolicy)
                        return newPolicy
                    }
                    return values.policy
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
                s.eventTriggers,
                s.urlTriggers,
                s.urlBlocklist,
            ],
            (
                sampleRate,
                minimumDurationMilliseconds,
                linkedFeatureFlag,
                eventTriggers,
                urlTriggers,
                urlBlocklist
            ): Trigger[] => [
                {
                    type: TriggerType.URL_MATCH,
                    enabled: urlTriggers.length > 0,
                    urls: urlTriggers,
                },
                {
                    type: TriggerType.EVENT,
                    enabled: eventTriggers.length > 0,
                    events: eventTriggers,
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
        setMatchType: () => actions.savePolicy(),
        setSampleRate: () => actions.savePolicy(),
        setMinimumDurationMilliseconds: () => actions.savePolicy(),
        setLinkedFeatureFlag: () => actions.savePolicy(),
        setEventTriggers: () => actions.savePolicy(),
        setUrlTriggers: () => actions.savePolicy(),
        setUrlBlocklist: () => actions.savePolicy(),
    })),
])
