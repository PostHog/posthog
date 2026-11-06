import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'

import { PostHogTeamCohortBanner } from '~/layout/panel-layout/navbar/PostHogTeamCohortBanner'

/**
 * The notices the classic nav footer shows, at the foot of the Today sidebar.
 * TODO: these still render their LemonUI views. Give each a quill sibling before the flag ships.
 */
export function TodaySidebarNotices(): JSX.Element {
    return (
        <div className="mt-auto flex flex-none flex-col gap-1 px-2 pb-2 empty:hidden">
            <DebugNotice isCollapsed={false} />
            <PostHogTeamCohortBanner isCollapsed={false} />
            <NavPanelAdvertisement isCollapsed={false} />
        </div>
    )
}
