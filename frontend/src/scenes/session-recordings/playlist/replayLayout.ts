export type ReplayLayout = 'classic' | 'watch'

export function watchLayoutOfferedByFlag(flagValue: string | boolean | undefined): boolean {
    return flagValue === 'test'
}

export function replayLayoutFrom(flagValue: string | boolean | undefined, preferClassicLayout: boolean): ReplayLayout {
    return watchLayoutOfferedByFlag(flagValue) && !preferClassicLayout ? 'watch' : 'classic'
}

/** The watch layout only shapes players whose host opted in, which is the replay playlist. */
export function playerUsesWatchLayout(layout: ReplayLayout, logicProps: { watchLayout?: boolean }): boolean {
    return layout === 'watch' && !!logicProps.watchLayout
}
