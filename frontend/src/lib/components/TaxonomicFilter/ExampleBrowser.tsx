import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, Link, Spinner } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TZLabel } from 'lib/components/TZLabel'

import { EXAMPLE_COUNT, isSelectableValue, taxonomicExampleBrowserLogic } from './taxonomicExampleBrowserLogic'
import { TaxonomicFilterGroupType } from './types'

export function ExampleBrowser(): JSX.Element {
    const {
        exampleSource,
        examples,
        examplesLoading,
        currentExample,
        exampleIndex,
        hasPreviousExample,
        hasNextExample,
        hidePostHogProperties,
        visibleProperties,
        supportsValueSelection,
        exploreUrl,
    } = useValues(taxonomicExampleBrowserLogic)
    const {
        closeExampleBrowser,
        showNextExample,
        showPreviousExample,
        setHidePostHogProperties,
        selectExampleKey,
        selectExampleValue,
    } = useActions(taxonomicExampleBrowserLogic)

    const eventNoun =
        exampleSource?.eventNames.length === 1 ? (
            <>
                <PropertyKeyInfo value={exampleSource.eventNames[0]} type={TaxonomicFilterGroupType.Events} /> events
            </>
        ) : (
            'events'
        )

    return (
        <div className="taxonomic-infinite-list flex flex-col h-full" data-attr="taxonomic-example-browser">
            <div className="flex items-center gap-1 px-2 pt-2">
                <LemonButton
                    size="xsmall"
                    icon={<IconArrowLeft />}
                    onClick={closeExampleBrowser}
                    data-attr="taxonomic-example-browser-back"
                    tooltip="Back to the list"
                />
                <span className="font-semibold truncate">Properties on recent {eventNoun}</span>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-2 py-1">
                <LemonCheckbox
                    size="small"
                    checked={hidePostHogProperties}
                    onChange={setHidePostHogProperties}
                    label="Hide PostHog properties"
                    data-attr="taxonomic-example-browser-hide-posthog"
                />
                {examples.length > 0 && (
                    <div className="flex items-center gap-1 text-xs text-secondary">
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronLeft />}
                            onClick={showPreviousExample}
                            disabledReason={hasPreviousExample ? undefined : 'This is the most recent event'}
                            data-attr="taxonomic-example-browser-previous"
                        />
                        <span translate="no">
                            {exampleIndex + 1} of {examples.length}
                        </span>
                        <LemonButton
                            size="xsmall"
                            icon={<IconChevronRight />}
                            onClick={showNextExample}
                            disabledReason={hasNextExample ? undefined : 'No older events loaded'}
                            data-attr="taxonomic-example-browser-next"
                        />
                    </div>
                )}
            </div>
            <div className="flex-1 min-h-0 max-h-80 overflow-y-auto px-2">
                {examplesLoading ? (
                    <div className="flex items-center justify-center h-full py-8">
                        <Spinner className="text-3xl" />
                    </div>
                ) : !currentExample ? (
                    <div className="flex flex-col gap-1 items-center text-center text-secondary py-8">
                        <span>No {eventNoun} in the last 30 days.</span>
                        <span>Search for a property name instead, or explore more to widen the date range.</span>
                    </div>
                ) : visibleProperties.length === 0 ? (
                    <div className="flex flex-col gap-1 items-center text-center text-secondary py-8">
                        <span>No matching properties on this event.</span>
                        <span>
                            {hidePostHogProperties
                                ? 'Untick "Hide PostHog properties" or try another event.'
                                : 'Try another event.'}
                        </span>
                    </div>
                ) : (
                    <ul className="flex flex-col divide-y divide-border">
                        {visibleProperties.map(([key, value]) => (
                            <li key={key} className="flex items-center gap-1 py-0.5 min-w-0">
                                <LemonButton
                                    size="xsmall"
                                    className="shrink-0 max-w-1/2"
                                    onClick={() => selectExampleKey(key)}
                                    tooltip="Filter on this property"
                                    data-attr="taxonomic-example-browser-key"
                                >
                                    <PropertyKeyInfo value={key} type={TaxonomicFilterGroupType.EventProperties} />
                                </LemonButton>
                                {supportsValueSelection && isSelectableValue(value) ? (
                                    <LemonButton
                                        size="xsmall"
                                        className="min-w-0"
                                        onClick={() => selectExampleValue(key, String(value))}
                                        tooltip="Filter on this exact value"
                                        data-attr="taxonomic-example-browser-value"
                                    >
                                        <span className="font-mono truncate">{String(value)}</span>
                                    </LemonButton>
                                ) : (
                                    <span className="font-mono text-xs text-secondary truncate px-2">
                                        {JSON.stringify(value)}
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-2 py-1 border-t border-border text-xs text-secondary">
                <span>
                    {currentExample ? (
                        <>
                            Seen <TZLabel time={currentExample.timestamp} />
                        </>
                    ) : (
                        `Shows up to ${EXAMPLE_COUNT} recent events`
                    )}
                </span>
                {exploreUrl && (
                    <Link to={exploreUrl} target="_blank" data-attr="taxonomic-example-browser-explore">
                        Explore more
                    </Link>
                )}
            </div>
        </div>
    )
}
