import { Link } from 'lib/lemon-ui/Link'

import { TopCitedSource } from '../types'

export function TopCitedSourcesList({
    sources,
    onViewAll,
}: {
    sources: TopCitedSource[]
    onViewAll?: () => void
}): JSX.Element {
    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold">Top cited sources</h3>
                <Link className="text-xs text-primary" onClick={onViewAll}>
                    View all
                </Link>
            </div>
            <div className="space-y-3">
                {sources.slice(0, 6).map((source) => (
                    <div key={source.domain} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <img
                                src={`https://www.google.com/s2/favicons?domain=${source.domain}&sz=128`}
                                alt=""
                                className="w-5 h-5 rounded"
                            />
                            <span className="text-sm">{source.domain}</span>
                        </div>
                        <span className="text-sm">
                            <strong>{source.responseCount}</strong> <span className="text-muted">responses</span>
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}
