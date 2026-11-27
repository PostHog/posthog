import './DefinitionPopoverGrid.scss'

interface GridProps {
    children: React.ReactNode
    cols?: number
}

export function DefinitionPopoverGrid({ children, cols }: GridProps): JSX.Element {
    return (
        <div
            className="definition-popover-grid"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ gridTemplateColumns: `repeat(${cols}, auto)` }}
        >
            {children}
        </div>
    )
}
