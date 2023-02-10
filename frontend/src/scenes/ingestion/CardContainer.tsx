import { PanelFooter } from './panels/PanelComponents'
import './panels/Panels.scss'
import { IngestionState } from 'scenes/ingestion/ingestionLogic'

export function CardContainer({
    children,
    nextProps,
    onContinue,
    finalStep = false,
}: {
    children: React.ReactNode
    nextProps?: Partial<IngestionState>
    onContinue?: () => void
    finalStep?: boolean
}): JSX.Element {
    return (
        // We want a forced width for this view only
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ maxWidth: 800 }}>
            {children}
            <div>
                {nextProps && <PanelFooter nextProps={nextProps} onContinue={onContinue} finalStep={finalStep} />}
            </div>
        </div>
    )
}
