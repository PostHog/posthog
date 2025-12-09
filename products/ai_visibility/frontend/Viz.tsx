import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { vizLogic } from './vizLogic'

const Viz: React.FC = () => {
    const { domain, scrapeResult, scrapeResultLoading } = useValues(vizLogic)
    const { setDomain, scrapeDomain, clearResult } = useActions(vizLogic)

    return (
        <div className="flex flex-col items-center gap-4 p-8">
            <div className="w-full max-w-2xl">
                <h1 className="text-3xl font-bold mb-6">Domain scraper</h1>

                <div className="flex gap-2 mb-6">
                    <LemonInput
                        type="text"
                        value={domain}
                        onChange={(value) => setDomain(value)}
                        placeholder="Enter domain (e.g., example.com)"
                        className="flex-1"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && domain.trim()) {
                                scrapeDomain()
                            }
                        }}
                    />
                    <LemonButton
                        type="primary"
                        onClick={scrapeDomain}
                        loading={scrapeResultLoading}
                        disabled={!domain.trim() || scrapeResultLoading}
                    >
                        Run
                    </LemonButton>
                </div>

                {scrapeResultLoading && (
                    <div className="flex justify-center py-8">
                        <Spinner />
                    </div>
                )}

                {scrapeResult && !scrapeResultLoading && (
                    <LemonCard className="p-6">
                        <div className="flex justify-between items-start mb-4">
                            <h2 className="text-xl font-semibold">Results</h2>
                            <LemonButton size="small" onClick={clearResult}>
                                Clear
                            </LemonButton>
                        </div>
                        <div className="space-y-3">
                            <div>
                                <span className="font-medium">Business name: </span>
                                <span>{scrapeResult.business_name}</span>
                            </div>
                            <div>
                                <span className="font-medium">Business type: </span>
                                <span>{scrapeResult.business_type}</span>
                            </div>
                            <div>
                                <span className="font-medium">Domain: </span>
                                <span className="text-muted">{scrapeResult.domain}</span>
                            </div>
                        </div>
                    </LemonCard>
                )}
            </div>
        </div>
    )
}

export default Viz
