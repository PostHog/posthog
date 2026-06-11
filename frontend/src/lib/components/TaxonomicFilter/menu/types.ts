/**
 * Shared types for the dropdown-menu-fronted taxonomic filter.
 *
 * See `../headless/UX_SPEC.md` for the full design.
 */
import { AnyPropertyFilter } from '~/types'

import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from '../types'

/** Stamped on the legacy `taxonomic filter *` telemetry events so the A/B arms
 *  are distinguishable by an explicit property rather than a feature-flag join.
 *  Legacy emits `legacy-control` / `legacy-pill`. */
export const TAXONOMIC_FILTER_SURFACE = 'rebuild-menu'

/** A single selectable entry — what the picker commits when chosen. */
export interface MenuFilterEntry {
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    name: string
    friendlyLabel?: string
    recentPropertyFilter?: AnyPropertyFilter
    recentLabel?: string
}

/** Synthetic categories the combobox panel can be drilled into. */
export type DrillCategory = 'all' | 'recent' | 'pinned' | TaxonomicFilterGroupType

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

/** Row context the combobox forwards on commit so the legacy `taxonomic filter
 *  item selected` event (emitted from the final-commit funnel, not on row click)
 *  can still carry the row's position and origin. Absent for commits that don't
 *  originate from a combobox row (DWH config form, HogQL editor). */
export interface CommitSelectionContext {
    /** Active scope chip the row sat under (legacy `activeTab`); undefined on the All/Recent/Pinned meta scopes. */
    groupType: TaxonomicFilterGroupType | undefined
    /** Zero-based row position in the rendered list; undefined if the committed
     *  entry isn't in the rendered list (kept absent rather than a sentinel). */
    position: number | undefined
    wasFromRecents: boolean
    wasFromPinnedList: boolean
}

export type CommitFn = (
    entry: MenuFilterEntry,
    extra?: Record<string, unknown>,
    selection?: CommitSelectionContext
) => void

export type { TaxonomicFilterGroup, TaxonomicFilterGroupType, TaxonomicFilterValue, TaxonomicDefinitionTypes }
