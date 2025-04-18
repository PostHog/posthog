import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

export function PlayerSidebarSessionSummaryTab(): JSX.Element {
    return (
        <div className="flex flex-col overflow-auto bg-primary px-2 py-1 h-full deprecated-space-y-1">
            <PlayerSidebarSessionSummary />
        </div>
    )
}
