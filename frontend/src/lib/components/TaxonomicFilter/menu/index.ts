/**
 * Dropdown-menu-fronted taxonomic filter — fresh rebuild.
 *
 * See `../headless/UX_SPEC.md` for the design reference.
 *
 *   <TaxonomicFilterHeadless.Root taxonomicGroupTypes={...} onChange={...}>
 *     <TaxonomicFilterMenu />
 *   </TaxonomicFilterHeadless.Root>
 */
export { TaxonomicFilterMenu } from './TaxonomicFilterMenu'
export type { TaxonomicFilterMenuProps, TriggerState as MenuFilterTriggerState } from './TaxonomicFilterMenu'

export { MenuFilterCombobox } from './Combobox'
export type { MenuFilterComboboxProps } from './Combobox'

export { MenuFilterDwhConfig } from './DwhFlow'
export type { MenuFilterDwhConfigProps } from './DwhFlow'

export { MenuFilterHogQLEditor } from './HogQLEditor'
export type { MenuFilterHogQLEditorProps } from './HogQLEditor'

export { MenuFilterHeader } from './Header'
export type { MenuFilterHeaderProps } from './Header'

export { PreviewPane as MenuFilterPreviewPane } from './PreviewPane'
export type { PreviewPaneProps as MenuFilterPreviewPaneProps } from './PreviewPane'

export type {
    CommitFn as MenuFilterCommitFn,
    DrillCategory as MenuFilterDrillCategory,
    MenuFilterEntry,
    MenuFilterState,
    PageHeader as MenuFilterPageHeader,
} from './types'
