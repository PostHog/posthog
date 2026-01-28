import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

interface PositionButtonProps {
    position: string
    isActive: boolean
    onClick: () => void
    disabled?: boolean
    alignmentClasses: [string, string]
    ariaLabel: string
    toolbar?: boolean
}

export const PositionButton = ({
    position,
    isActive,
    onClick,
    disabled,
    alignmentClasses,
    ariaLabel,
    toolbar,
}: PositionButtonProps): JSX.Element => {
    const [itemsClass, justifyClass] = alignmentClasses

    // toolbar styles are whack - some custom classes and inline styles are required
    // for this to work in toolbar context
    const dotClassName = toolbar
        ? cn('size-3 rounded-xs', isActive ? 'bg-accent' : 'group-hover:bg-accent/40')
        : cn(
              'size-3 rounded-xs border',
              isActive ? 'bg-accent border-transparent' : 'group-hover:bg-accent/40 border-primary'
          )

    const dotStyle = toolbar && !isActive ? { border: '1px solid #d0d5dd' } : undefined

    return (
        <ButtonPrimitive
            size="base"
            onClick={onClick}
            active={isActive}
            type="button"
            disabled={disabled}
            inert={disabled}
            className={cn('justify-center text-xs w-full h-8 p-1', disabled ? 'cursor-not-allowed' : 'group')}
            aria-label={ariaLabel}
            title={position}
        >
            <div className={`flex w-full h-full ${itemsClass} ${justifyClass}`}>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div className={dotClassName} style={dotStyle} />
            </div>
        </ButtonPrimitive>
    )
}
