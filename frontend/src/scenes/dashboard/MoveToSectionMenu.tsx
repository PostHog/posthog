import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

export interface MoveToSectionDestination {
    groupId: string
    label: string
}

export interface MoveToSectionMenuProps {
    destinations: MoveToSectionDestination[]
    onMove: (groupId: string) => void
}

export function MoveToSectionMenu({ destinations, onMove }: MoveToSectionMenuProps): JSX.Element | null {
    if (destinations.length === 0) {
        return null
    }

    return (
        <LemonMenu
            items={destinations.map((destination) => ({
                label: destination.label,
                onClick: () => onMove(destination.groupId),
            }))}
        >
            <LemonButton fullWidth data-attr="dashboard-tile-move-to-section">
                Move to section
            </LemonButton>
        </LemonMenu>
    )
}
