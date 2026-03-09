import { afterMount, connect, kea, listeners, path } from 'kea'

import { proxyLogic } from 'scenes/settings/environment/proxyLogic'

import type { onboardingReverseProxyLogicType } from './onboardingReverseProxyLogicType'

export const onboardingReverseProxyLogic = kea<onboardingReverseProxyLogicType>([
    path(['scenes', 'onboarding', 'onboardingReverseProxyLogic']),
    connect(() => ({
        values: [proxyLogic, ['proxyRecords', 'proxyRecordsLoading']],
        actions: [proxyLogic, ['acknowledgeCloudflareOptIn', 'showForm', 'createRecord']],
    })),
    listeners(({ actions }) => ({
        createRecord: () => {
            actions.acknowledgeCloudflareOptIn() // Acknowledge Cloudflare opt-in when a record is successfully created
        },
    })),
    afterMount(({ actions }) => {
        actions.showForm() // During onboarding we have the proxy form open by default
    }),
])
