/** The Data records a scene reports as a recent. Kept apart from `todayData.ts`, so scene logics skip the nav tree. */

// pinned: shortcut `type` values. Pins are saved with them, so renaming one drops everyone's pins of that type.
export const TODAY_DATA_RECENT_TYPES = ['event_definition', 'property_definition', 'data_source', 'data_model'] as const

export type TodayDataRecentType = (typeof TODAY_DATA_RECENT_TYPES)[number]

export interface TodayDataRecent {
    type: TodayDataRecentType
    name: string
    href: string
    /** The record's id, for records that are also starred by id elsewhere, such as a source on the Sources page. */
    ref?: string
}
