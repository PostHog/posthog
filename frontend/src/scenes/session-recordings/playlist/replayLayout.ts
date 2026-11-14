export type ReplayLayout = 'classic' | 'compact' | 'youtube' | 'landing'

export const NEW_REPLAY_LAYOUTS: ReplayLayout[] = ['compact', 'youtube', 'landing']

export const STAFF_REPLAY_LAYOUTS: ReplayLayout[] = ['classic', 'compact', 'youtube']

export function offeredReplayLayout(flagValue: string | boolean | undefined): ReplayLayout | null {
    return typeof flagValue === 'string' && (NEW_REPLAY_LAYOUTS as string[]).includes(flagValue)
        ? (flagValue as ReplayLayout)
        : null
}

export function replayLayoutFrom(
    flagValue: string | boolean | undefined,
    preferClassicLayout: boolean,
    staffOverride: ReplayLayout | null = null
): ReplayLayout {
    if (staffOverride) {
        return staffOverride
    }
    const offered = offeredReplayLayout(flagValue)
    return offered && !preferClassicLayout ? offered : 'classic'
}

export function staffReplayLayout(storedOverride: ReplayLayout | null): ReplayLayout {
    return storedOverride && STAFF_REPLAY_LAYOUTS.includes(storedOverride) ? storedOverride : 'classic'
}

export function isNewReplayLayout(layout: ReplayLayout): boolean {
    return layout !== 'classic'
}

/** The watch layout only shapes players whose host opted in, which is the replay playlist. */
export function playerUsesWatchLayout(layout: ReplayLayout, logicProps: { watchLayout?: boolean }): boolean {
    return isNewReplayLayout(layout) && !!logicProps.watchLayout
}

export function isFeedReplayLayout(layout: ReplayLayout): boolean {
    return layout === 'youtube'
}
