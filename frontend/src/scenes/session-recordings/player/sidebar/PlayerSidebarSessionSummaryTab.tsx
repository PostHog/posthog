import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

export function PlayerSidebarSessionSummaryTab(): JSX.Element {
    return (
        <div className="flex flex-col overflow-auto bg-card px-2 py-1 h-full">
            <PlayerSidebarSessionSummary />
        </div>
    )
}
