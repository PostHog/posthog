import { BuiltLogic } from 'kea'

import {
    DataWarehousePopoverField,
    DefinitionPopoverRenderer,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import {
    ActionFilter as ActionFilterType,
    ChartDisplayCategory,
    FunnelExclusionLegacy,
    InsightType,
    PropertyOperator,
} from '~/types'

import { LocalFilter } from '../entityFilterLogic'
import { entityFilterLogicType } from '../entityFilterLogicType'

export enum MathAvailability {
    All,
    ActorsOnly,
    FunnelsOnly,
    CalendarHeatmapOnly,
    BoxPlotOnly,
    None,
}

export interface ActionFilterRowProps {
    logic: BuiltLogic<entityFilterLogicType>
    filter: LocalFilter
    index: number
    typeKey: string
    mathAvailability: MathAvailability
    singleFilter?: boolean
    hideFilter?: boolean // Hides the local filter options
    hideRename?: boolean // Hides the rename option
    hideDuplicate?: boolean // Hides the duplicate option
    hideDeleteBtn?: boolean // Choose to hide delete btn. You can use the onClose function passed into customRow{Pre|Suf}fix to render the delete btn anywhere
    showCombine?: boolean // Show the combine inline events option
    insightType?: InsightType // The type of insight (trends, funnels, etc.)
    propertyFiltersPopover?: boolean
    onRenameClick?: () => void // Used to open rename modal
    showSeriesIndicator?: boolean // Show series badge
    seriesIndicatorType?: 'alpha' | 'numeric' // Series badge shows A, B, C | 1, 2, 3
    filterCount: number
    sortable: boolean
    customRowSuffix?:
        | string
        | JSX.Element
        | ((props: {
              filter: ActionFilterType | FunnelExclusionLegacy
              index: number
              onClose: () => void
          }) => JSX.Element) // Custom suffix element to show in each row
    hasBreakdown: boolean // Whether the current graph has a breakdown filter applied
    showNestedArrow?: boolean // Show nested arrows to the left of property filter buttons
    actionsTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for actions selector
    propertiesTaxonomicGroupTypes?: TaxonomicFilterGroupType[] // Which tabs to show for property filters
    disabled?: boolean
    readOnly?: boolean
    renderRow?: ({
        seriesIndicator,
        filter,
        suffix,
        propertyFiltersButton,
        renameRowButton,
        deleteButton,
    }: Record<string, JSX.Element | string | undefined>) => JSX.Element // build your own row given these components
    trendsDisplayCategory: ChartDisplayCategory | null
    /** Whether properties shown should be limited to just numerical types */
    showNumericalPropsOnly?: boolean
    /** Only allow these math types in the selector */
    allowedMathTypes?: readonly string[]
    /** Fields to display in the data warehouse filter popover */
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    /** Whether to add left padding to the filters div to align with suffix content */
    filtersLeftPadding?: boolean
    /** Doc link to show in the tooltip of the New Filter button */
    addFilterDocLink?: string
    /** Doc link to show in the tooltip of the Combine events button */
    inlineEventsDocLink?: string
    /** Allow adding non-captured events */
    allowNonCapturedEvents?: boolean
    hogQLGlobals?: Record<string, any>
    definitionPopoverRenderer?: DefinitionPopoverRenderer
    operatorAllowlist?: PropertyOperator[]
}

export interface MathSelectorProps {
    math?: string
    mathGroupTypeIndex?: number | null
    mathAvailability: MathAvailability
    index: number
    disabled?: boolean
    disabledReason?: string
    onMathSelect: (index: number, value: any) => any
    trendsDisplayCategory: ChartDisplayCategory | null
    style?: React.CSSProperties
    size?: LemonButtonProps['size']
    /** Only allow these math types in the selector */
    allowedMathTypes?: readonly string[]
    query?: Record<string, any>
}
