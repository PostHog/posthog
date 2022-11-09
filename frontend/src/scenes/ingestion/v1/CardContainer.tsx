import { PanelFooter } from './panels/PanelComponents'
import './panels/Panels.scss'

export function CardContainer({
    children,
    showFooter,
}: {
    children: React.ReactNode
    showFooter?: boolean
}): JSX.Element {
    return (
        // We want a forced width for this view only
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ maxWidth: 800 }}>
            {children}
            <div>{showFooter && <PanelFooter />}</div>
        </div>
    )
}
