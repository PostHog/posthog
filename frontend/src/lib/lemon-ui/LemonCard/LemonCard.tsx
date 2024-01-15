import './LemonCard.scss'

export interface LemonCardProps {
    hoverEffect?: boolean
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    focused?: boolean
}

export function LemonCard({ hoverEffect = true, className, children, onClick, focused }: LemonCardProps): JSX.Element {
    return (
        <div
            className={`LemonCard ${hoverEffect && 'LemonCard--hoverEffect'} border ${
                focused ? 'border-2 border-primary' : 'border-border'
            } rounded p-6 bg-bg-light ${className}`}
            onClick={onClick}
        >
            {children}
        </div>
    )
}
