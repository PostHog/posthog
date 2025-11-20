import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

interface PositionButtonProps {
    position: string
    isActive: boolean
    onClick: () => void
    disabled?: boolean
    alignmentClasses: [string, string]
    ariaLabel: string
}

export const PositionButton = ({
    position,
    isActive,
    onClick,
    disabled,
    alignmentClasses,
    ariaLabel,
}: PositionButtonProps): JSX.Element => {
    const [itemsClass, justifyClass] = alignmentClasses

    return (
        <ButtonPrimitive
            size="lg"
            onClick={onClick}
            active={isActive}
            type="button"
            disabled={disabled}
            inert={disabled}
            className={cn('justify-center text-xs w-full p-1', disabled ? 'cursor-not-allowed' : 'group')}
            aria-label={ariaLabel}
            title={position}
        >
            <div className={`flex w-full h-full ${itemsClass} ${justifyClass}`}>
                <div
                    className={cn(
                        'size-4 border border-transparent rounded-xs',
                        isActive ? 'bg-accent' : 'group-hover:bg-accent/40 border-primary'
                    )}
                />
            </div>
        </ButtonPrimitive>
    )
}
