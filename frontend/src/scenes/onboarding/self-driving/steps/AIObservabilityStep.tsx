import { useState } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { AIObservabilitySDKInstructions } from 'scenes/onboarding/legacy/sdks/ai-observability/AIObservabilitySDKInstructions'
import { ALL_SDKS } from 'scenes/onboarding/legacy/sdks/allSDKs'

import { SDKKey } from '~/types'

const PROVIDER_OPTIONS = Object.keys(AIObservabilitySDKInstructions).map((key) => ({
    value: key as SDKKey,
    label: ALL_SDKS.find((sdk) => sdk.key === key)?.name ?? key,
}))

/**
 * Goal-conditional step for `maintain_ai`: the generic wizard install doesn't wire LLM instrumentation,
 * so this step carries the per-provider instructions. The goal's finish line is the first AI
 * traces coming in.
 */
export function AIObservabilityStep({
    onContinue,
    onSkip,
}: {
    onContinue: () => void
    onSkip: () => void
}): JSX.Element {
    const [provider, setProvider] = useState<SDKKey>(SDKKey.OPENAI)
    const Instructions = AIObservabilitySDKInstructions[provider]

    return (
        <div className="flex flex-col gap-5">
            <div className="flex items-center justify-center gap-2">
                <span className="text-secondary text-sm">My AI app uses</span>
                <LemonSelect
                    size="small"
                    value={provider}
                    onChange={(value) => value && setProvider(value)}
                    options={PROVIDER_OPTIONS}
                />
            </div>
            {Instructions && (
                <div className="border rounded p-4 text-left">
                    <Instructions />
                </div>
            )}
            <div className="flex flex-col items-center gap-1 pt-2">
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
                <LemonButton type="tertiary" size="small" onClick={onSkip}>
                    Skip for now
                </LemonButton>
            </div>
        </div>
    )
}
