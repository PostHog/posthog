import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export function LemonAddGoalLineButton({
    onClick,
    className,
}: {
    onClick: () => void
    className: string
}): JSX.Element {
    return (
        <LemonButton type="secondary" onClick={onClick} icon={<IconPlusSmall />} size="small" className={className}>
            Add goal line
        </LemonButton>
    )
}
