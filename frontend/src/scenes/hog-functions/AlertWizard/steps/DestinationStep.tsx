import { useActions, useValues } from 'kea'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { WizardDestination, alertWizardLogic } from '../alertWizardLogic'
import { WizardCard } from './WizardCard'

export function DestinationStep(): JSX.Element {
    const { destinations, allDestinations, usedDestinationKeys, existingAlertsLoading } = useValues(alertWizardLogic)
    const { setDestinationKey } = useActions(alertWizardLogic)
    const selectedDestinationKeys = new Set(destinations.map((destination) => destination.key))
    const destinationsByKey = new Map(allDestinations.map((destination) => [destination.key, destination]))
    const preferredExtraDestinationKeys = ['gitlab', 'linear', 'microsoft-teams']
    const preferredExtraDestinations = preferredExtraDestinationKeys
        .map((key) => destinationsByKey.get(key))
        .filter((destination): destination is WizardDestination => !!destination)
        .filter((destination) => !selectedDestinationKeys.has(destination.key))
    const remainingExtraDestinations = allDestinations.filter(
        (destination) =>
            !selectedDestinationKeys.has(destination.key) && !preferredExtraDestinationKeys.includes(destination.key)
    )
    const moreDestinations = [...preferredExtraDestinations, ...remainingExtraDestinations]

    if (existingAlertsLoading) {
        return (
            <div className="space-y-4">
                <div>
                    <h2 className="text-xl font-semibold mb-1">Where should we send alerts?</h2>
                    <p className="text-secondary text-sm">Choose your preferred notification channel</p>
                </div>
                <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div
                            key={i}
                            className="group relative text-left rounded-lg border border-border bg-bg-light p-5 w-full animate-pulse"
                        >
                            <div className="flex items-center gap-4">
                                <div className="shrink-0 w-10 h-10 rounded bg-border" />
                                <div>
                                    <h3 className="font-semibold text-base mb-0.5 relative">
                                        <span className="invisible">Placeholder</span>
                                        <span className="absolute inset-y-0 left-0 flex items-center">
                                            <span className="h-3 w-24 rounded bg-border block" />
                                        </span>
                                    </h3>
                                    <p className="text-sm mb-0 relative">
                                        <span className="invisible">Placeholder description</span>
                                        <span className="absolute inset-y-0 left-0 flex items-center">
                                            <span className="h-2.5 w-48 rounded bg-border block" />
                                        </span>
                                    </p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Where should we send alerts?</h2>
                <p className="text-secondary text-sm">Choose your preferred notification channel</p>
            </div>
            <div className="space-y-3">
                {destinations.map((destination: WizardDestination) => (
                    <WizardCard
                        key={destination.key}
                        icon={<HogFunctionIcon src={destination.icon} size="medium" />}
                        name={destination.name}
                        description={destination.description}
                        badge={usedDestinationKeys.has(destination.key) ? 'Previously used' : undefined}
                        onClick={() => setDestinationKey(destination.key)}
                    />
                ))}
            </div>
            {moreDestinations.length > 0 && (
                <details>
                    <summary className="cursor-pointer text-sm text-secondary hover:text-primary select-none">
                        More destinations
                    </summary>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
                        {moreDestinations.map((destination) => (
                            <button
                                key={destination.key}
                                type="button"
                                onClick={() => setDestinationKey(destination.key)}
                                className="group flex cursor-pointer items-center gap-2 rounded-md border border-border bg-bg-light px-3 py-2 text-left transition-all duration-150 hover:border-border-bold hover:shadow-sm active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
                            >
                                <HogFunctionIcon src={destination.icon} size="small" />
                                <span className="text-sm font-medium truncate transition-colors group-hover:text-link">
                                    {destination.name}
                                </span>
                            </button>
                        ))}
                    </div>
                </details>
            )}
        </div>
    )
}
