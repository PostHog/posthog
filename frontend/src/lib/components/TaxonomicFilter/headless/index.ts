/**
 * Headless TaxonomicFilter primitives.
 *
 *   <TaxonomicFilter.Root taxonomicGroupTypes={...} onChange={...}>
 *     <TaxonomicFilter.Input />
 *     <TaxonomicFilter.Categories />
 *     <TaxonomicFilter.Panel />
 *   </TaxonomicFilter.Root>
 *
 * Each primitive accepts an `className` (single, no plural classNames slot)
 * and most accept an explicit render override for full control.
 */
import { TaxonomicAutocomplete, TaxonomicFilterAutocompleteInput } from './AutocompleteInput'
import { TaxonomicFilterCategories } from './Categories'
import { TaxonomicFilterInput } from './Input'
import { TaxonomicFilterPanel } from './Panel'
import { TaxonomicFilterRoot } from './Root'

export const TaxonomicFilterHeadless = {
    Root: TaxonomicFilterRoot,
    Input: TaxonomicFilterInput,
    AutocompleteInput: TaxonomicFilterAutocompleteInput,
    Autocomplete: TaxonomicAutocomplete,
    Categories: TaxonomicFilterCategories,
    Panel: TaxonomicFilterPanel,
}

export {
    TaxonomicAutocomplete,
    useTaxonomicAutocomplete,
    useTaxonomicAutocompleteCategories,
    useTaxonomicAutocompleteItemDetails,
    useTaxonomicAutocompleteShortcutItems,
} from './AutocompleteInput'
export { TaxonomicFilterContext, useTaxonomicFilterContext } from './context'
export type { TaxonomicFilterRootProps } from './Root'
export type { TaxonomicFilterInputProps } from './Input'
export type {
    TaxonomicAutocompleteCategory,
    TaxonomicAutocompleteCategoryMode,
    TaxonomicAutocompleteChipsProps,
    TaxonomicAutocompleteConfigureState,
    TaxonomicAutocompleteConfigureViewProps,
    TaxonomicAutocompleteContentProps,
    TaxonomicAutocompleteDetailsState,
    TaxonomicAutocompleteDetailsViewProps,
    TaxonomicAutocompleteEmptyProps,
    TaxonomicAutocompleteEntry,
    TaxonomicAutocompleteHeaderProps,
    TaxonomicAutocompleteInputProps,
    TaxonomicAutocompleteItemDetails,
    TaxonomicAutocompleteItemsProps,
    TaxonomicAutocompleteListProps,
    TaxonomicAutocompleteMenuTriggerProps,
    TaxonomicAutocompletePage,
    TaxonomicAutocompletePageKind,
    TaxonomicAutocompleteRootProps,
    TaxonomicAutocompleteRootViewProps,
    TaxonomicAutocompleteSeed,
    TaxonomicAutocompleteSegmentedTriggerProps,
    TaxonomicAutocompleteTriggerProps,
    TaxonomicAutocompleteTriggerState,
    TaxonomicFilterAutocompleteInputProps,
} from './AutocompleteInput'
export type { TaxonomicFilterCategoriesProps, TaxonomicFilterCategoryRenderProps } from './Categories'
export type { TaxonomicFilterPanelProps, TaxonomicFilterRowRenderProps } from './Panel'
