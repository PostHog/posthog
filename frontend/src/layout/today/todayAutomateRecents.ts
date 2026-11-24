/** The Automate records a scene reports as a recent. Kept apart from `todayAutomate.ts`, so scene logics skip the nav tree. */

// pinned: shortcut `type` values. Pins are saved with them, so renaming one drops everyone's pins of that type.
// A destination uses its file system type, because the backend keeps only `hog_function/*` shortcuts to the environment
// they were pinned in, and a destination belongs to one environment.
export const TODAY_AUTOMATE_RECENT_TYPES = ['workflow', 'hog_function/destination', 'subscription', 'scout'] as const

export type TodayAutomateRecentType = (typeof TODAY_AUTOMATE_RECENT_TYPES)[number]

export interface TodayAutomateRecent {
    type: TodayAutomateRecentType
    name: string
    href: string
}
