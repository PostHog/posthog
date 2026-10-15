import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { infiniteListLogic } from './infiniteListLogic'
import { EventMatchHint, taxonomicEventMatchLogic } from './taxonomicEventMatchLogic'

function listOfNames(names: string[]): string {
    if (names.length <= 1) {
        return names.join('')
    }
    return `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}`
}

function EventMatchHintMessage({ hint }: { hint: EventMatchHint }): JSX.Element {
    if (hint.kind === 'unsent') {
        return (
            <div className="flex flex-col items-center gap-y-1" data-attr="taxonomic-event-match-unsent">
                <span className="text-secondary text-center max-w-80">
                    This looks like <strong>{listOfNames(hint.events.map((event) => event.display_name))}</strong>,
                    which this project hasn't sent yet.
                </span>
            </div>
        )
    }

    return (
        <div className="flex flex-col items-center gap-y-1" data-attr="taxonomic-event-match-value">
            <span className="text-secondary text-center max-w-80">
                This looks like a value, not an event name. Pick the property that holds it, then filter on the value.
            </span>
        </div>
    )
}

export function TaxonomicEventMatchSuggestions(): JSX.Element | null {
    const { props } = useMountedLogic(infiniteListLogic)
    const logic = taxonomicEventMatchLogic(props)
    const { suggestedEvents, isMatching, hint } = useValues(logic)
    const { selectEventMatch } = useActions(logic)

    if (isMatching) {
        return (
            <div className="flex items-center gap-1 text-secondary" data-attr="taxonomic-event-match-loading">
                <Spinner className="text-sm" />
                <span>Looking for events you might mean</span>
            </div>
        )
    }

    if (suggestedEvents.length === 0) {
        return hint ? <EventMatchHintMessage hint={hint} /> : null
    }

    return (
        <div className="flex flex-col items-center gap-y-1" data-attr="taxonomic-event-match">
            <span className="text-secondary">Did you mean one of these events?</span>
            <div className="flex flex-wrap justify-center gap-1">
                {suggestedEvents.map((match) => (
                    <LemonButton
                        key={match.name}
                        type="secondary"
                        size="xsmall"
                        // pinned: data-attr, autocapture and the flag's success metric read it
                        data-attr="taxonomic-event-match-suggestion"
                        onClick={() => selectEventMatch(match)}
                    >
                        {match.display_name}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
