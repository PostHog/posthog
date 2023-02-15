import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonEventName } from 'scenes/actions/EventName'
import { useActions, useValues } from 'kea'
import { activationFinderLogic } from './activationFinderLogic'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

export function ActivationFinderScene(): JSX.Element {
    const { initialEvent, finalEvent, initialPropertyFilters, finalPropertyFilters } = useValues(activationFinderLogic)
    const { setInitialEvent, setFinalEvent, setInitialPropertyFilters, setFinalPropertyFilters } =
        useActions(activationFinderLogic)

    return (
        <div className="ActivationFinderScene">
            <PageHeader title="Activation Finder" />
            <p className="mb-8 ml-0">
                Use our handy tool to identify some groups of actions that make a good candidate for your product's
                Activation milestone.
            </p>

            {/* Section to add first event */}
            <div className="border border-border rounded p-4 my-8">
                <h2 className="flex flex-row items-center">
                    <SeriesGlyph>1</SeriesGlyph>
                    <span className="ml-2">Set your initial event</span>
                </h2>
                <p>
                    This should be when your users first start using your product. For example, "user signed up" or
                    "user installed my product."
                </p>
                <div className="flex flex-row">
                    <LemonEventName value={initialEvent} onChange={setInitialEvent} />
                    <PropertyFilters
                        propertyFilters={initialPropertyFilters}
                        onChange={setInitialPropertyFilters}
                        pageKey={'activation-finder-initial-event'}
                        style={{ marginBottom: 0, marginTop: 0, marginLeft: 8 }}
                        eventNames={[]}
                    />
                </div>
            </div>

            {/* Section to select up to 15 candidate events */}

            {/* Section to select the final event */}
            <div className="border border-border rounded p-4 my-8">
                <h2 className="flex flex-row items-center">
                    <SeriesGlyph>3</SeriesGlyph>
                    <span className="ml-2">Set your final event</span>
                </h2>
                <p>
                    This should be the final conversion event - oftentimes it's the thing that translates to revenue.
                    For example, "user subscribed" or "user purchased product."
                </p>
                <div className="flex flex-row">
                    <LemonEventName value={finalEvent} onChange={setFinalEvent} />
                    <PropertyFilters
                        propertyFilters={finalPropertyFilters}
                        onChange={setFinalPropertyFilters}
                        pageKey={'activation-finder-final-event'}
                        style={{ marginBottom: 0, marginTop: 0, marginLeft: 8 }}
                        eventNames={[]}
                    />
                </div>
            </div>

            {/* Section to show results */}
        </div>
    )
}

export const scene: SceneExport = {
    component: ActivationFinderScene,
}
