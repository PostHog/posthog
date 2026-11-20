import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import {
    Card,
    CardGroup,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Heading,
    Skeleton,
    Text,
} from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { WizardDestination, alertWizardLogic } from '../alertWizardLogic'
import { QuillWizardCard } from './QuillWizardCard'

// The destination step lives below the hog functions scene, so it loads the icon on first render.
const HogFunctionIcon = lazyWithRetry(() =>
    import('scenes/hog-functions/configuration/HogFunctionIcon').then((m) => ({ default: m.HogFunctionIcon }))
)

function DestinationStepHeading(): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Where should we send alerts?
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Choose your preferred notification channel
            </Text>
        </div>
    )
}

export function QuillDestinationStep(): JSX.Element {
    const { primaryDestinations, extraDestinations, usedDestinationKeys, existingAlertsLoading } =
        useValues(alertWizardLogic)
    const { setDestinationKey } = useActions(alertWizardLogic)

    if (existingAlertsLoading) {
        return (
            <div className="flex flex-col gap-3">
                <DestinationStepHeading />
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <DestinationStepHeading />

            <CardGroup size="sm">
                {primaryDestinations.map((destination: WizardDestination) => (
                    <QuillWizardCard
                        key={destination.key}
                        icon={
                            <Suspense fallback={null}>
                                <HogFunctionIcon src={destination.icon} size="medium" />
                            </Suspense>
                        }
                        name={destination.name}
                        description={destination.description}
                        badge={usedDestinationKeys.has(destination.key) ? 'Previously used' : undefined}
                        onClick={() => setDestinationKey(destination.key)}
                    />
                ))}
            </CardGroup>

            {extraDestinations.length > 0 && (
                <>
                    {/* Loads the icons before the section opens, so they do not pop in. */}
                    {extraDestinations.map(
                        (destination: WizardDestination) =>
                            destination.icon && (
                                <img key={destination.key} src={destination.icon} className="hidden" aria-hidden />
                            )
                    )}
                    <Collapsible>
                        <CollapsibleTrigger>More destinations</CollapsibleTrigger>
                        <CollapsibleContent className="flex flex-col gap-2">
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                                {extraDestinations.map((destination: WizardDestination) => (
                                    <Card key={destination.key} size="sm" className="p-0">
                                        <button
                                            type="button"
                                            onClick={() => setDestinationKey(destination.key)}
                                            className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                        >
                                            <Suspense fallback={null}>
                                                <HogFunctionIcon src={destination.icon} size="small" />
                                            </Suspense>
                                            <Text size="xs" weight="medium" className="m-0 truncate" render={<span />}>
                                                {destination.name}
                                            </Text>
                                        </button>
                                    </Card>
                                ))}
                            </div>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                More destinations are available in the traditional editor.
                            </Text>
                        </CollapsibleContent>
                    </Collapsible>
                </>
            )}
        </div>
    )
}
