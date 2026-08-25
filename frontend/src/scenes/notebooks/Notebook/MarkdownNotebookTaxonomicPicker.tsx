import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

export type MarkdownNotebookTaxonomicPickerProps = {
    isOpen: boolean
    title: string
    groupType: TaxonomicFilterGroupType
    groupTypes?: TaxonomicFilterGroupType[]
    onClose: () => void
    onSelect: (value: TaxonomicFilterValue, group: TaxonomicFilterGroup) => void
}

/** Entity picker for insert-menu commands whose entity has a taxonomic group (feature flags,
 * cohorts, …) — the taxonomic filter brings search and pagination for free. */
export function MarkdownNotebookTaxonomicPicker({
    isOpen,
    title,
    groupType,
    groupTypes,
    onClose,
    onSelect,
}: MarkdownNotebookTaxonomicPickerProps): JSX.Element {
    return (
        <LemonModal
            title={title}
            onClose={onClose}
            isOpen={isOpen}
            footer={
                <LemonButton type="secondary" data-attr="markdown-notebook-taxonomic-picker-cancel" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            {/* Remount per open so a previous search query doesn't carry over */}
            {isOpen ? (
                <TaxonomicFilter
                    groupType={groupType}
                    taxonomicGroupTypes={groupTypes || [groupType]}
                    onChange={(group, value) => {
                        if (value !== null && value !== undefined && value !== '') {
                            onSelect(value, group)
                        }
                    }}
                />
            ) : null}
        </LemonModal>
    )
}
