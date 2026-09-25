import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSwitch, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { sidebarToolMeta } from '../../sidebarToolMeta'
import { appsItemName } from './appsCatalog'
import { navAppsTabLogic } from './navAppsTabLogic'

export function ConfigureStarredModal(): JSX.Element {
    const {
        configureStarredOpen,
        rankedConfigurableApps,
        selectedAppStars,
        pendingAppStars,
        starSaveError,
        appRecommendationQuery,
        appRecommendationsEnabled,
        appRankingsLoading,
        appRankingError,
    } = useValues(navAppsTabLogic)
    const { setConfigureStarredOpen, setAppStarred, setAppRecommendationQuery } = useActions(navAppsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)

    return (
        <LemonModal
            title="Configure starred"
            description="Choose which apps appear in Starred. Changes save automatically."
            isOpen={configureStarredOpen}
            onClose={() => setConfigureStarredOpen(false)}
            width={640}
            footer={
                <div className="flex items-center gap-4 w-full flex-wrap">
                    <div className="text-xs text-secondary flex-1" role="status">
                        {Object.keys(pendingAppStars).length > 0
                            ? 'Saving changes…'
                            : 'Tip: Drag starred items in the sidebar to rearrange them.'}
                    </div>
                    <LemonButton
                        type="primary"
                        data-attr="configure-starred-done"
                        onClick={() => setConfigureStarredOpen(false)}
                    >
                        Done
                    </LemonButton>
                </div>
            }
        >
            {appRecommendationsEnabled && (
                <div className="flex flex-col gap-2 mb-4">
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
                        {[
                            'Track website visitors',
                            'Query databases',
                            'Debug errors',
                            'Watch user sessions',
                            'Run A/B tests',
                        ].map((example) => (
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
            )}
            {starSaveError && (
                <LemonBanner type="error" className="mb-3">
                    {starSaveError}
                </LemonBanner>
            )}
            <div className="flex flex-col gap-2 group/colorful-product-icons colorful-product-icons-true">
                {!shortcutDataHasLoaded ? (
                    <Spinner />
                ) : (
                    rankedConfigurableApps.map((item) => {
                        const { description, docsHref } = sidebarToolMeta(item)
                        const label = appsItemName(item)
                        return (
                            <LemonSwitch
                                key={item.path}
                                className="py-2"
                                checked={!!selectedAppStars[item.path]}
                                onChange={(starred) => setAppStarred(item.path, starred)}
                                data-attr="configure-starred-app-toggle"
                                aria-label={label}
                                bordered
                                fullWidth
                                label={
                                    <span className="flex items-center gap-2">
                                        <span className="text-lg shrink-0 flex items-center">
                                            {iconForType(item.iconType, item.iconColor)}
                                        </span>
                                        <span className="flex flex-col">
                                            <span className="flex items-center gap-2">
                                                {label}
                                                {docsHref && (
                                                    <Link
                                                        to={docsHref}
                                                        target="_blank"
                                                        className="text-xs font-normal"
                                                        onClick={(event) => event.stopPropagation()}
                                                    >
                                                        Docs
                                                    </Link>
                                                )}
                                            </span>
                                            {description && (
                                                <span className="text-xs font-normal text-secondary">
                                                    {description}
                                                </span>
                                            )}
                                        </span>
                                    </span>
                                }
                            />
                        )
                    })
                )}
            </div>
        </LemonModal>
    )
}
