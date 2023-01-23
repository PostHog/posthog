import { LemonButton } from '../LemonButton/LemonButton'
import { IconClose } from '../icons'

export type LemonPillProps = {
    children: React.ReactNode
    onClick: () => void
    onDelete: () => void
}

export function LemonPill({ children, onClick, onDelete }: LemonPillProps): JSX.Element {
    return (
        <div
            className="h-8 px-4 py-1 rounded-4xl flex items-center bg-primary-alt-highlight text-primary-alt cursor-pointer"
            onClick={onClick}
        >
            {children}
            <LemonButton className="ml-1" size="small" status="danger" icon={<IconClose />} onClick={onDelete} />
        </div>
    )
}
