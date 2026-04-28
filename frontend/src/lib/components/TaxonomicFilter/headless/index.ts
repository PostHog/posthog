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
import { TaxonomicFilterAutocompleteInput } from './AutocompleteInput'
import { TaxonomicFilterCategories } from './Categories'
import { TaxonomicFilterInput } from './Input'
import { TaxonomicFilterPanel } from './Panel'
import { TaxonomicFilterRoot } from './Root'

export const TaxonomicFilterHeadless = {
    Root: TaxonomicFilterRoot,
    Input: TaxonomicFilterInput,
    AutocompleteInput: TaxonomicFilterAutocompleteInput,
    Categories: TaxonomicFilterCategories,
    Panel: TaxonomicFilterPanel,
}

export { TaxonomicFilterContext, useTaxonomicFilterContext } from './context'
export type { TaxonomicFilterRootProps } from './Root'
export type { TaxonomicFilterInputProps } from './Input'
export type { TaxonomicFilterAutocompleteInputProps } from './AutocompleteInput'
export type { TaxonomicFilterCategoriesProps, TaxonomicFilterCategoryRenderProps } from './Categories'
export type { TaxonomicFilterPanelProps, TaxonomicFilterRowRenderProps } from './Panel'
