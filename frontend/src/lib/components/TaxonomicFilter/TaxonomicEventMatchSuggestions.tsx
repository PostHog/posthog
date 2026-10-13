import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicEventMatchLogic } from './taxonomicEventMatchLogic'

export function TaxonomicEventMatchSuggestions(): JSX.Element | null {
    const { props } = useMountedLogic(infiniteListLogic)
    const logic = taxonomicEventMatchLogic(props)
    const { suggestedEvents, isMatching } = useValues(logic)
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
        return null
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
