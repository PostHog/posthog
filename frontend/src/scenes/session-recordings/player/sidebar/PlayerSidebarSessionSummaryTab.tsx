import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

export function PlayerSidebarSessionSummaryTab(): JSX.Element {
    return (
        <div className="bg-primary flex h-full flex-col overflow-auto px-2 py-1">
            <PlayerSidebarSessionSummary />
        </div>
    )
}
