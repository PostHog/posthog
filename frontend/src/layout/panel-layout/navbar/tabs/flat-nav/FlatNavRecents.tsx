import { NavRecentItems } from '../NavRecentItems'
import { FlatNavSection } from './FlatNavSection'

export function FlatNavRecents(): JSX.Element {
    return (
        <FlatNavSection label="Recents" info="Items you viewed recently, most recent first.">
            <NavRecentItems />
        </FlatNavSection>
    )
}
