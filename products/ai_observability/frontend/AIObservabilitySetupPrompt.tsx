import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/queries/schema/schema-general'

import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'

type Thing = 'generation' | 'trace'

export function AIObservabilitySetupPrompt({
    children,
    className,
    thing = 'generation',
}: {
    children: React.ReactNode
    thing?: Thing
    className?: string
}): JSX.Element {
    const { hasSentAiEvent, hasSentAiEventLoading } = useValues(aiObservabilitySharedLogic)

    return hasSentAiEventLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasSentAiEvent ? (
        <IngestionStatusCheck className={className} thing={thing} />
    ) : (
        <>{children}</>
    )
}

function IngestionStatusCheck({ className, thing }: { className?: string; thing: Thing }): JSX.Element {
    return (
        <ProductIntroduction
            productName="AI observability"
            thingName={`LLM ${thing}`}
            titleOverride={`No LLM ${thing} events have been detected!`}
            description="To use AI observability, please instrument your LLM calls with the PostHog SDK."
            isEmpty={true}
            productKey={ProductKey.AI_OBSERVABILITY}
            className={className}
            docsURL="https://posthog.com/docs/ai-observability/installation"
        />
    )
}
