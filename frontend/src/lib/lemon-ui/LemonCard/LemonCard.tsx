import './LemonCard.scss'

export interface LemonCardProps {
    hoverEffect?: boolean
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    focused?: boolean
    'data-attr'?: string
}

export function LemonCard({
    hoverEffect = true,
    className,
    children,
    onClick,
    focused,
    ...props
}: LemonCardProps): JSX.Element {
    return (
        <div
            className={`LemonCard ${hoverEffect && 'LemonCard--hoverEffect'} border ${
                focused ? 'border-2 border-primary' : 'border-border'
            } rounded p-6 bg-bg-light ${className}`}
            onClick={onClick}
            {...props}
        >
            {children}
        </div>
    )
}
