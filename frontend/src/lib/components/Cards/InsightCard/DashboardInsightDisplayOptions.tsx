import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { useInsightDisplayOptions } from '~/queries/nodes/InsightViz/insightDisplayOptions'

// The insight editor's "Options" menu, surfaced as a submenu in the dashboard card ⋯ menu. Edits
// persist to the saved insight via the card's `setQuery` wiring (see InsightCard).
export function DashboardInsightDisplayOptions(): JSX.Element | null {
    const { items } = useInsightDisplayOptions()

    if (items.length === 0) {
        return null
    }

    return (
        <>
            <LemonDivider />
            <LemonMenu
                items={items}
                closeOnClickInside={false}
                placement="right-start"
                fallbackPlacements={['left-start']}
            >
                <LemonButton fullWidth>Display options</LemonButton>
            </LemonMenu>
        </>
    )
}
