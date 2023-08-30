import './LemonCard.scss'

export interface LemonCardProps {
    hoverEffect?: boolean
    className?: string
    children?: React.ReactNode
}

export function LemonCard({ hoverEffect = true, className, children }: LemonCardProps): JSX.Element {
    return (
        <div
            className={`LemonCard ${
                hoverEffect && 'LemonCard--hoverEffect'
            } border border-border rounded-lg p-6 bg-white ${className}`}
        >
            {children}
        </div>
    )
}
