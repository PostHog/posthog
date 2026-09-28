import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonLabel,
    LemonModal,
    LemonSwitch,
    LemonTextArea,
    Spinner,
} from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { HomepageConfiguration } from '~/layout/scenes/HomepageConfiguration'

import { iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { navProductsTabLogic } from './navProductsTabLogic'
import { productsItemName } from './productsCatalog'

export function CustomizeSidebarModal(): JSX.Element {
    const {
        customizeSidebarOpen,
        rankedConfigurableApps,
        appMatchGroups,
        selectedAppStars,
        pendingAppStars,
        starSaveError,
        appRecommendationQuery,
        appRecommendationsEnabled,
        appRankingsLoading,
        appRankingError,
    } = useValues(navProductsTabLogic)
    const { setCustomizeSidebarOpen, setProductStarred, setAppRecommendationQuery } = useActions(navProductsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)

    return (
        <LemonModal
            title="Customize sidebar"
            description="Changes save automatically."
            isOpen={customizeSidebarOpen}
            onClose={() => setCustomizeSidebarOpen(false)}
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
                        onClick={() => setCustomizeSidebarOpen(false)}
                    >
                        Done
                    </LemonButton>
                </div>
            }
        >
            <section className="flex flex-col gap-2 mb-6">
                <div>
                    <LemonLabel>Homepage</LemonLabel>
                    <p className="text-xs text-secondary mb-0">The page that opens when you select Home.</p>
                </div>
                <HomepageConfiguration />
            </section>
            <div className="mb-2">
                <LemonLabel>Starred</LemonLabel>
                <p className="text-xs text-secondary mb-0">Starred products appear below Home in the sidebar.</p>
            </div>
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
                        {['Track website visitors', 'Query databases', 'Debug errors', 'Run A/B tests'].map(
                            (example) => (
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
                            )
                        )}
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
                    [
                        { matching: true, items: appMatchGroups?.matching ?? rankedConfigurableApps },
                        { matching: false, items: appMatchGroups?.other ?? [] },
                    ]
                        .filter((group) => group.matching || group.items.length > 0)
                        .map((group) => (
                            <section
                                key={String(group.matching)}
                                aria-label={
                                    appMatchGroups ? (group.matching ? 'Matching apps' : 'Other apps') : 'All apps'
                                }
                                className={cn('flex flex-col gap-2', !group.matching && 'mt-8 border-t pt-4')}
                            >
                                {appMatchGroups &&
                                    (group.matching ? (
                                        <h3 className="text-sm font-semibold mb-0">Matching apps</h3>
                                    ) : (
                                        <div>
                                            <h3 className="text-sm font-semibold mb-1">Other apps</h3>
                                            <p className="text-xs text-secondary mb-2">
                                                These apps are below the match threshold. You can still star them.
                                            </p>
                                        </div>
                                    ))}
                                {appMatchGroups && group.matching && group.items.length === 0 && (
                                    <p className="text-sm text-secondary mb-0">
                                        No apps meet the match threshold. Try another description or choose from the
                                        apps below.
                                    </p>
                                )}
                                {group.items.map((item) => {
                                    const { description, docsHref } = sidebarProductMeta(item)
                                    const label = productsItemName(item)
                                    return (
                                        <LemonSwitch
                                            key={item.path}
                                            className={cn(
                                                'py-2',
                                                !group.matching &&
                                                    'opacity-60 hover:opacity-100 focus-within:opacity-100'
                                            )}
                                            checked={!!selectedAppStars[item.path]}
                                            onChange={(starred) => setProductStarred(item.path, starred)}
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
                                })}
                            </section>
                        ))
                )}
            </div>
        </LemonModal>
    )
}
