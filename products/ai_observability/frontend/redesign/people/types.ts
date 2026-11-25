export interface PersonFirstSeen {
    firstSeen: string | null
    /** The earliest date the read covered. Activity before it was never read. */
    checkedFrom: string
    /** No AI activity in the lookback before the range. */
    isNew: boolean
}
