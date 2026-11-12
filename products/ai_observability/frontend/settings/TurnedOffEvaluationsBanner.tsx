import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { llmProviderKeysLogic } from './llmProviderKeysLogic'

/** Offers to turn back on the evaluations a provider key problem turned off, once that key validates again. */
export function TurnedOffEvaluationsBanner(): JSX.Element | null {
    const { turnedOffEvaluations, turnedOffEvaluationsLoading, providerKeys } = useValues(llmProviderKeysLogic)
    const { turnEvaluationsBackOn } = useActions(llmProviderKeysLogic)

    if (!turnedOffEvaluations) {
        return null
    }
    const { evaluations } = turnedOffEvaluations
    const keyName = providerKeys.find((key) => key.id === turnedOffEvaluations.keyId)?.name ?? 'This key'
    const outOfQuota = evaluations.some((evaluation) => evaluation.status_reason === 'provider_key_quota_exceeded')
    const names = evaluations.map((evaluation) => evaluation.name).join(', ')

    return (
        <LemonBanner
            type="info"
            action={{
                children: evaluations.length === 1 ? 'Turn it back on' : 'Turn them back on',
                onClick: () => turnEvaluationsBackOn(),
                loading: turnedOffEvaluationsLoading,
                'data-attr': 'llma-provider-key-turn-evaluations-back-on',
            }}
        >
            {`${keyName} works again, but ${pluralize(evaluations.length, 'evaluation')} it turned off ${evaluations.length === 1 ? 'is' : 'are'} still off: ${names}.`}
            {outOfQuota && ' If the quota ran out, add credits with the provider first, or they turn off again.'}
        </LemonBanner>
    )
}
