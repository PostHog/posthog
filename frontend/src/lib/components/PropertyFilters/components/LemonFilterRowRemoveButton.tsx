import { IconTrash, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface LemonFilterRowRemoveButtonProps {
    orFiltering?: boolean
    onRemove: () => void
    size: 'xsmall' | 'small' | 'medium'
}

export function LemonFilterRowRemoveButton({
    orFiltering,
    onRemove,
    size,
}: LemonFilterRowRemoveButtonProps): JSX.Element {
    return (
        <LemonButton
            icon={orFiltering ? <IconTrash /> : <IconX />}
            onClick={() => onRemove()}
            size={size}
            className="ml-2"
            noPadding
        />
    )
}
