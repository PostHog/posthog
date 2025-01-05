import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { PlayerSidebarOverviewGrid } from 'scenes/session-recordings/player/sidebar/PlayerSidebarOverviewGrid'

export const PanelOverview = (): JSX.Element => {
    return (
        <>
            <PersonDisplay person={sessionPerson} withIcon withCopyButton />
            <PlayerSidebarOverviewGrid />
        </>
    )
}
