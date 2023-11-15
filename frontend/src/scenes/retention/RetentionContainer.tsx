import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionTable } from './RetentionTable'
import { LemonDivider } from '@posthog/lemon-ui'
import { RetentionModal } from './RetentionModal'

export function RetentionContainer({
    inCardView,
    inSharedMode,
}: {
    inCardView?: boolean
    inSharedMode?: boolean
}): JSX.Element {
    return (
        <div className="RetentionContainer">
            {inCardView ? (
                <RetentionTable inCardView={inCardView} />
            ) : (
                <>
                    <div className="RetentionContainer__graph">
                        <RetentionLineGraph inSharedMode={inSharedMode} />
                    </div>
                    <LemonDivider />
                    <div className="RetentionContainer__table overflow-x-auto">
                        <RetentionTable inCardView={inCardView} />
                    </div>
                    <RetentionModal />
                </>
            )}
        </div>
    )
}
