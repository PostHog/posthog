import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionTable } from './RetentionTable'
import './RetentionContainer.scss'
import { LemonDivider } from '@posthog/lemon-ui'

export function RetentionContainer({
    inCardView,
    inSharedMode,
}: {
    inCardView?: boolean
    inSharedMode?: boolean
}): JSX.Element {
    return (
        <div className="RetentionContainer space-y-4">
            {inCardView ? (
                <RetentionTable inCardView={inCardView} />
            ) : (
                <>
                    <RetentionLineGraph inSharedMode={inSharedMode} />
                    <LemonDivider />
                    <div className="overflow-x-auto">
                        <RetentionTable inCardView={inCardView} />
                    </div>
                </>
            )}
        </div>
    )
}
