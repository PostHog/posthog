import { Checkbox } from '@posthog/quill'

interface PageSelectionCheckboxProps {
    pageIds: string[]
    selectedIds: string[]
    onChange: (pageIds: string[], selected: boolean) => void
    label: string
}

export function PageSelectionCheckbox({
    pageIds,
    selectedIds,
    onChange,
    label,
}: PageSelectionCheckboxProps): JSX.Element {
    const selectedOnPage = pageIds.filter((id) => selectedIds.includes(id)).length
    const allSelected = pageIds.length > 0 && selectedOnPage === pageIds.length
    return (
        <Checkbox
            aria-label={label}
            checked={allSelected}
            indeterminate={selectedOnPage > 0 && !allSelected}
            disabled={pageIds.length === 0}
            onCheckedChange={(checked: boolean) => onChange(pageIds, checked)}
        />
    )
}
