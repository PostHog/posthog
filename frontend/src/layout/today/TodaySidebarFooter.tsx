import { useValues } from 'kea'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayOrgMenu } from './TodayOrgMenu'
import { TodayProjectMenu } from './TodayProjectMenu'
import { todayShellLogic } from './todayShellLogic'

/**
 * The phone layout's footer. The phone has no top bar and no rail, so the menus that sit there on a larger screen
 * sit here instead: organization, project, then account.
 */
export function TodaySidebarFooter(): JSX.Element {
    const { phoneHeaderHasProjectMenu } = useValues(todayShellLogic)
    return (
        <div className="grid flex-none grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1 border-t border-[var(--border)] px-2 pt-2 pb-2">
            <TodayOrgMenu />
            <div className="flex min-w-0">{!phoneHeaderHasProjectMenu && <TodayProjectMenu />}</div>
            <TodayAccountMenu placement="phone-footer" />
        </div>
    )
}
