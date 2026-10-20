import { IconTrash, IconX } from '@posthog/icons'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'

export interface QuillFilterRowRemoveButtonProps {
    orFiltering?: boolean
    onRemove: () => void
}

export function QuillFilterRowRemoveButton({ orFiltering, onRemove }: QuillFilterRowRemoveButtonProps): JSX.Element {
    return (
        <QuillIconButton
            label="Remove filter"
            icon={orFiltering ? <IconTrash /> : <IconX />}
            onClick={onRemove}
            className="ml-2"
        />
    )
}
