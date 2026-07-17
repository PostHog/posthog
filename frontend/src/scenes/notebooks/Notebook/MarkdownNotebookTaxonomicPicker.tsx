import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

export type MarkdownNotebookTaxonomicPickerProps = {
    isOpen: boolean
    title: string
    groupType: TaxonomicFilterGroupType
    onClose: () => void
    onSelect: (value: TaxonomicFilterValue) => void
}

/** Entity picker for insert-menu commands whose entity has a taxonomic group (feature flags,
 * cohorts, …) — the taxonomic filter brings search and pagination for free. */
export function MarkdownNotebookTaxonomicPicker({
    isOpen,
    title,
    groupType,
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
                    taxonomicGroupTypes={[groupType]}
                    onChange={(_, value) => {
                        if (value !== null && value !== undefined && value !== '') {
                            onSelect(value)
                        }
                    }}
                />
            ) : null}
        </LemonModal>
    )
}
