import { LemonButton } from '@posthog/lemon-ui'
import { Empty } from 'antd'

export function FunnelCorrelationTableEmptyState({
    showLoadResultsButton,
    loadResults,
}: {
    showLoadResultsButton: boolean
    loadResults: () => void
}): JSX.Element {
    console.log(showLoadResultsButton)
    return (
        <>
            {showLoadResultsButton ? (
                <LemonButton onClick={loadResults} className="m-auto" type="secondary">
                    Load results
                </LemonButton>
            ) : (
                <Empty />
            )}
        </>
    )
}
