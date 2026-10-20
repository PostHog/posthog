import { ChartDisplayCategory } from '~/types'

import { MathAvailability } from './types'

/** What the row-end controls of a series row need, independent of the UI library that draws them. */
export interface ActionFilterRowControlsArgs {
    index: number
    propertyFilterCount: number
    propertyFiltersVisible: boolean
    propertyFiltersDisabledReason?: string
    addFilterDocLink?: string
    inlineEventsDocLink?: string
    /** Rename, duplicate, combine and delete go in the row menu rather than inline. */
    enablePopup: boolean
    canCombine: boolean
    onToggleFilters: () => void
    onRename: () => void
    onDuplicate: () => void
    onCombine: () => void
    onDelete: () => void
    menu: {
        isTrendsContext: boolean
        isFunnelContext: boolean
        isStepOptional: (step: number) => boolean
        math?: string
        mathGroupTypeIndex?: number | null
        mathAvailability: MathAvailability
        trendsDisplayCategory: ChartDisplayCategory | null
        readOnly: boolean
        query: Record<string, any>
        filter: { optionalInFunnel?: boolean }
        hideRename: boolean
        hideDuplicate: boolean
        hideDeleteBtn: boolean
        singleFilter: boolean
        onMathSelect: (index: number, value: string | undefined) => void
        onUpdateOptional: (checked: boolean) => void
    }
}

export interface ActionFilterRowControls {
    propertyFiltersButton: JSX.Element
    renameRowButton: JSX.Element
    duplicateRowButton: JSX.Element
    combineInlineButton: JSX.Element
    deleteButton: JSX.Element
    /** The row menu holding the actions when `enablePopup` is set. */
    menu: JSX.Element
}
