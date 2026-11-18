import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { taxonomicSearchIntentLogic } from './taxonomicSearchIntentLogic'
import { TaxonomicFilterLogicProps } from './types'

function lowercaseFirst(text: string): string {
    return text.charAt(0).toLowerCase() + text.slice(1)
}

export function TaxonomicSearchIntentBanner({
    taxonomicFilterLogicProps,
}: {
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}): JSX.Element | null {
    const logic = taxonomicSearchIntentLogic(taxonomicFilterLogicProps)
    const { suggestedSwitch } = useValues(logic)
    const { acceptSuggestedSwitch } = useActions(logic)

    if (!suggestedSwitch) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mt-1"
            hideIcon
            action={{
                children: `Switch to ${lowercaseFirst(suggestedSwitch.groupName)}`,
                onClick: acceptSuggestedSwitch,
                // pinned: data-attr, autocapture and the experiment read it
                'data-attr': 'taxonomic-search-intent-switch',
            }}
        >
            Looking for {lowercaseFirst(suggestedSwitch.groupName)}?
        </LemonBanner>
    )
}
