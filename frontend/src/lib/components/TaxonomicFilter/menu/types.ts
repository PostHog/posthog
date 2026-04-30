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

/** Synthetic categories the combobox panel can be drilled into. */
export type DrillCategory = 'all' | 'recent' | 'pinned' | TaxonomicFilterGroupType

/** Top-level state machine. One union type, one transition per action. */
export type MenuFilterState =
    | { kind: 'closed' }
    | { kind: 'menu' }
    | { kind: 'combobox'; drillTo: DrillCategory }
    | { kind: 'dwh-pick' }
    | { kind: 'dwh-config'; table: TaxonomicDefinitionTypes; group: TaxonomicFilterGroup }
    | { kind: 'hogql-edit' }

/** Common header info every popover sub-page shares. */
export interface PageHeader {
    title: string
    /** Called when the back button (or Esc) fires. */
    onBack: () => void
}

export type CommitFn = (entry: MenuFilterEntry, extra?: Record<string, unknown>) => void

export type { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue, TaxonomicDefinitionTypes }
