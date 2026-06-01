/**
 * Shared types for the dropdown-menu-fronted taxonomic filter.
 *
 * See `../headless/UX_SPEC.md` for the full design.
 */
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from '../types'

/** A single selectable entry — what the picker commits when chosen. */
export interface MenuFilterEntry {
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    name: string
    friendlyLabel?: string
}

/** Synthetic categories the combobox panel can be drilled into.
 *  - `'suggested'` mixes Recent ∪ Pinned across groups, mirroring the
 *    legacy popover's "Suggested step" view; the row's category label
 *    still names the original source group. */
export type DrillCategory = 'all' | 'recent' | 'pinned' | 'suggested' | TaxonomicFilterGroupType

/** Top-level state machine. One union type, one transition per action. */
export type MenuFilterState =
    | { kind: 'closed' }
    | { kind: 'menu' }
    | { kind: 'combobox'; drillTo: DrillCategory }
    | { kind: 'dwh-pick' }
    | {
          kind: 'dwh-config'
          table: TaxonomicDefinitionTypes
          group: TaxonomicFilterGroup
          /** Where the dialog was opened from — restored when X / Esc /
           *  overlay / Cancel fire so back navigation lands on the right
           *  surface ('menu' = jumped here from the trigger because a
           *  selection already existed; 'dwh-pick' = drilled down via the
           *  table picker). */
          origin: 'menu' | 'dwh-pick'
      }
    | { kind: 'hogql-edit' }

/** Common header info every popover sub-page shares. */
export interface PageHeader {
    title: string
    /** Called when the back button (or Esc) fires. */
    onBack: () => void
}

export type CommitFn = (entry: MenuFilterEntry, extra?: Record<string, unknown>) => void

export type { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue, TaxonomicDefinitionTypes }
