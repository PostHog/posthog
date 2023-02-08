import { PanelFooter } from './panels/PanelComponents'
import './panels/Panels.scss'
import { IngestionState } from 'scenes/ingestion/ingestionLogicV2'

export function CardContainer({
    children,
    nextProps,
    onContinue,
}: {
    children: React.ReactNode
    nextProps?: Partial<IngestionState>
    onContinue?: () => void
}): JSX.Element {
    return (
        // We want a forced width for this view only
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ maxWidth: 800 }}>
            {children}
            <div>{nextProps && <PanelFooter nextProps={nextProps} onContinue={onContinue} />}</div>
        </div>
    )
}
