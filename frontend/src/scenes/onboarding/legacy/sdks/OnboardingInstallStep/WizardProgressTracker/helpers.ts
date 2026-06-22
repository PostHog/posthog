import { type DisplayState } from '../wizardProgressTrackerLogic'

export function bannerTypeFor(state: DisplayState): 'ai' | 'success' | 'error' {
    if (state === 'completed') {
        return 'success'
    }
    if (state === 'error') {
        return 'error'
    }
    return 'ai'
}

export function headlineFor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return 'PostHog is set up.'
        case 'error':
            return 'The wizard hit a snag.'
        case 'connecting':
            return 'Reconnecting to the wizard…'
        default:
            return "You've got ~10 minutes back. Go explore."
    }
}

export function subLineFor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return 'Check your terminal — the wizard left a report of what it changed. Then hit Next.'
        case 'connecting':
            return 'restoring connection — your run is still going'
        default:
            return "Close the tab, poke around the product, grab some water — the wizard keeps going and leaves a report when it's done."
    }
}
