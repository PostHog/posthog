import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

// Items are computed in InsightMeta (always mounted) and passed down to avoid mounting
// useInsightDisplayOptions lazily inside the More popover overlay, which triggers kea logic
// mounts that cascade and close the popover before the user can interact with it.
export function DashboardInsightDisplayOptions({ items }: { items: LemonMenuItems }): JSX.Element | null {
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
