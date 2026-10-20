import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { navProductsTabLogic } from './navProductsTabLogic'

const EXAMPLE_QUERIES = ['Track website visitors', 'Query databases', 'Debug errors', 'Run A/B tests']

export function JevProductSuggestions(): JSX.Element {
    const { appRecommendationQuery, appRankingsLoading, appRankingError, appMatchGroups } =
        useValues(navProductsTabLogic)
    const { setAppRecommendationQuery } = useActions(navProductsTabLogic)

    return (
        <div className="flex flex-col gap-2">
            <LemonTextArea
                value={appRecommendationQuery}
                onChange={setAppRecommendationQuery}
                aria-label="Filter by jev"
                data-attr="configure-starred-jev-query"
                placeholder="Filter by jev. Tell us what you want to use PostHog for, and we'll suggest apps to use."
                minRows={2}
                maxRows={8}
                maxLength={2000}
            />
            <div className="flex flex-wrap items-center gap-1">
                <span className="text-xs text-secondary mr-1">For example</span>
                {EXAMPLE_QUERIES.map((example) => (
                    <LemonButton
                        key={example}
                        size="xsmall"
                        type="secondary"
                        data-attr="configure-starred-jev-example"
                        loading={appRankingsLoading && appRecommendationQuery === example}
                        onClick={() => setAppRecommendationQuery(example)}
                    >
                        {example}
                    </LemonButton>
                ))}
            </div>
            <div className="text-xs text-secondary flex items-center gap-2" role="status">
                {appRankingsLoading && appRecommendationQuery.trim() ? (
                    <>
                        <Spinner className="text-sm" />
                        <span>Finding apps for you…</span>
                    </>
                ) : appMatchGroups && appMatchGroups.matching.length === 0 ? (
                    <span>No apps meet the match threshold. Try another description or choose from the list.</span>
                ) : (
                    <span>All apps stay in the list. Suggestions appear first.</span>
                )}
                {appRecommendationQuery && (
                    <LemonButton
                        size="xsmall"
                        data-attr="configure-starred-jev-clear"
                        onClick={() => setAppRecommendationQuery('')}
                    >
                        Clear
                    </LemonButton>
                )}
            </div>
            {appRankingError && <LemonBanner type="warning">{appRankingError}</LemonBanner>}
        </div>
    )
}
