import { LemonButton, Link } from '@posthog/lemon-ui'
import { Empty } from 'antd'

export function FunnelCorrelationTableEmptyState({
    infoMessage = '',
    showLoadResultsButton,
    loadResults,
}: {
    infoMessage?: string
    showLoadResultsButton: boolean
    loadResults: () => void
}): JSX.Element {
    return (
        <>
            {showLoadResultsButton ? (
                <div>
                    <p style={{ margin: 'auto', maxWidth: 500 }}>
                        {infoMessage}{' '}
                        <Link to="https://posthog.com/manual/correlation">Learn more about correlation analysis.</Link>
                    </p>
                    <br />
                    <LemonButton onClick={loadResults} type="secondary" className="m-auto">
                        Load results
                    </LemonButton>
                </div>
            ) : (
                <Empty />
            )}
        </>
    )
}
