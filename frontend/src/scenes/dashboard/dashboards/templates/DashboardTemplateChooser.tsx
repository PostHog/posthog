import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'

import {
    dashboardTemplateChooserLogic,
    DashboardTemplateChooserExperimentVariant,
    DashboardTemplateChooserLogicProps,
    resolveDashboardTemplateChooserExperimentVariant,
} from './dashboardTemplateChooserLogic'
import { TemplateItem } from './DashboardTemplateItem'
import { DashboardTemplateItemSkeleton } from './DashboardTemplateItemSkeleton'
import { DashboardTemplateProps } from './dashboardTemplatesLogic'

export type DashboardTemplateChooserRootProps = DashboardTemplateProps & {
    /** When set (e.g. from `NewDashboardModal`), avoids a second feature-flag read so Kea keys stay in sync with parent `dashboardTemplateChooserLogic`. */
    experimentVariant?: DashboardTemplateChooserExperimentVariant
}

const gridClass = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4'

/** Wider cells — team tiles are horizontal rows, not poster cards. */
const teamTemplateGridClass = 'grid grid-cols-1 md:grid-cols-2 gap-3'

/** Single column on small viewports; two columns from `lg` up (modal/tablet often still feels “small” at `md`) */
const featuredGridClass = 'grid grid-cols-1 lg:grid-cols-2 gap-4'

function SimpleVariant(
    props: DashboardTemplateProps & { experimentVariant: DashboardTemplateChooserExperimentVariant }
): JSX.Element {
    const { experimentVariant, className, availabilityContexts, ...chooserProps } = props
    const logicProps: DashboardTemplateChooserLogicProps = { ...chooserProps, experimentVariant, availabilityContexts }
    const chooser = dashboardTemplateChooserLogic(logicProps)
    const {
        allTemplatesLoading,
        teamTemplates,
        officialTemplates,
        hasActiveFilter,
        showDashedEmptyState,
        showOfficialGrid,
        showBlankTile,
    } = useValues(chooser)
    const { templateTileClicked, blankTileClicked, setTemplateFilter } = useActions(chooser)

    return (
        <div className={cn('flex flex-col gap-6', className)}>
            {teamTemplates.length > 0 ? (
                <section>
                    <div className="mb-3">
                        <h3 className="text-base font-semibold m-0">Team templates</h3>
                        <p className="text-secondary text-sm m-0 mt-1">Templates saved for this project.</p>
                    </div>
                    <div className={teamTemplateGridClass}>
                        {teamTemplates.map((template, index) => (
                            <TemplateItem
                                key={template.id}
                                template={template}
                                onClick={() => templateTileClicked(template, 'team_section')}
                                index={index}
                                data-attr="create-dashboard-from-template-team"
                                showCover={false}
                            />
                        ))}
                    </div>
                </section>
            ) : null}
            {showDashedEmptyState ? (
                <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border bg-fill-secondary px-6 py-14 text-center">
                    <h4 className="m-0 text-base font-semibold">
                        {hasActiveFilter ? 'No templates match your search' : 'No templates to show here'}
                    </h4>
                    <p className="mt-2 mb-0 max-w-md text-secondary text-sm">
                        {hasActiveFilter
                            ? 'Try different keywords, clear the filter to see every template again, or start with a blank dashboard.'
                            : showBlankTile
                              ? 'Start with a blank dashboard, or check back later for new templates.'
                              : 'No templates are available in this context.'}
                    </p>
                    <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                        {showBlankTile ? (
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => blankTileClicked('main_grid')}
                                data-attr="create-dashboard-blank-inline-empty"
                            >
                                Blank dashboard
                            </LemonButton>
                        ) : null}
                        {hasActiveFilter ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => setTemplateFilter('')}
                                data-attr="clear-dashboard-template-filter"
                            >
                                Clear filter
                            </LemonButton>
                        ) : null}
                    </div>
                </div>
            ) : showOfficialGrid ? (
                <section>
                    <div className="mb-3">
                        <h3 className="text-base font-semibold m-0">PostHog templates</h3>
                        <p className="text-secondary text-sm m-0 mt-1">
                            Curated templates from PostHog to help you get started.
                        </p>
                    </div>
                    <div className={gridClass}>
                        {allTemplatesLoading
                            ? Array.from({ length: 3 }).map((_, i) => <DashboardTemplateItemSkeleton key={i} />)
                            : officialTemplates.map((template, index) => (
                                  <TemplateItem
                                      key={template.id}
                                      template={template}
                                      onClick={() => templateTileClicked(template, 'main_grid')}
                                      index={index}
                                      data-attr="create-dashboard-from-template"
                                      showFavourite={experimentVariant === 'simple' && template.is_featured}
                                  />
                              ))}
                    </div>
                </section>
            ) : null}
        </div>
    )
}

function NewLayoutVariant(
    props: DashboardTemplateProps & { experimentVariant: DashboardTemplateChooserExperimentVariant }
): JSX.Element {
    const { experimentVariant, className, availabilityContexts, ...chooserProps } = props
    const logicProps: DashboardTemplateChooserLogicProps = { ...chooserProps, experimentVariant, availabilityContexts }
    const chooser = dashboardTemplateChooserLogic(logicProps)
    const {
        allTemplatesLoading,
        teamTemplates,
        featuredTemplates,
        nonFeaturedOfficial,
        hasActiveFilter,
        showDashedEmptyState,
        allMatchesInFeaturedSection,
        showOfficialSection,
        showBlankTile,
    } = useValues(chooser)
    const { templateTileClicked, blankTileClicked, setTemplateFilter } = useActions(chooser)

    return (
        <div className={cn('flex flex-col gap-8', className)}>
            {featuredTemplates.length > 0 ? (
                <section>
                    <div className="mb-3">
                        <h3 className="text-base font-semibold m-0">Popular with teams like yours</h3>
                        <p className="text-secondary text-sm m-0 mt-1">
                            Users love these templates! Great starting points for your dashboards.
                        </p>
                    </div>
                    <div className={featuredGridClass}>
                        {featuredTemplates.map((template, index) => (
                            <TemplateItem
                                key={template.id}
                                template={template}
                                onClick={() => templateTileClicked(template, 'featured_row')}
                                index={index}
                                size="large"
                                showFavourite={template.is_featured}
                                data-attr="create-dashboard-from-template-featured"
                            />
                        ))}
                    </div>
                </section>
            ) : null}

            {teamTemplates.length > 0 ? (
                <section>
                    <div className="mb-3">
                        <h3 className="text-base font-semibold m-0">Team templates</h3>
                        <p className="text-secondary text-sm m-0 mt-1">Templates saved for this project.</p>
                    </div>
                    <div className={teamTemplateGridClass}>
                        {teamTemplates.map((template, index) => (
                            <TemplateItem
                                key={template.id}
                                template={template}
                                onClick={() => templateTileClicked(template, 'team_section')}
                                index={index}
                                showCover={false}
                                data-attr="create-dashboard-from-template-team"
                            />
                        ))}
                    </div>
                </section>
            ) : null}

            {showDashedEmptyState ? (
                <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-border bg-fill-secondary px-6 py-14 text-center">
                    <h4 className="m-0 text-base font-semibold">
                        {hasActiveFilter ? 'No templates match your search' : 'No templates to show here'}
                    </h4>
                    <p className="mt-2 mb-0 max-w-md text-secondary text-sm">
                        {hasActiveFilter
                            ? 'Try different keywords, clear the filter to see every template again, or start with a blank dashboard.'
                            : showBlankTile
                              ? 'Start with a blank dashboard, or check back later for new templates.'
                              : 'No templates are available in this context.'}
                    </p>
                    <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                        {showBlankTile ? (
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => blankTileClicked('main_grid')}
                                data-attr="create-dashboard-blank-inline-empty"
                            >
                                Blank dashboard
                            </LemonButton>
                        ) : null}
                        {hasActiveFilter ? (
                            <LemonButton
                                type="secondary"
                                onClick={() => setTemplateFilter('')}
                                data-attr="clear-dashboard-template-filter"
                            >
                                Clear filter
                            </LemonButton>
                        ) : null}
                    </div>
                </div>
            ) : showOfficialSection ? (
                <section>
                    <div className="mb-3">
                        <h3 className="text-base font-semibold m-0">Official templates</h3>
                        <p className="text-secondary text-sm m-0 mt-1">Browse official templates below.</p>
                    </div>
                    <div className={gridClass}>
                        {allTemplatesLoading ? (
                            <>
                                {Array.from({ length: 3 }).map((_, i) => (
                                    <DashboardTemplateItemSkeleton key={i} />
                                ))}
                            </>
                        ) : allMatchesInFeaturedSection ? (
                            <p className="col-span-full m-0 text-center text-secondary text-sm py-2">
                                Every template that matches is in Popular above.
                            </p>
                        ) : (
                            nonFeaturedOfficial.map((template, index) => (
                                <TemplateItem
                                    key={template.id}
                                    template={template}
                                    onClick={() => templateTileClicked(template, 'main_grid')}
                                    index={index}
                                    data-attr="create-dashboard-from-template"
                                />
                            ))
                        )}
                    </div>
                </section>
            ) : null}
        </div>
    )
}

export function DashboardTemplateChooser({
    experimentVariant: experimentVariantProp,
    ...props
}: DashboardTemplateChooserRootProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const variant: DashboardTemplateChooserExperimentVariant =
        experimentVariantProp ??
        resolveDashboardTemplateChooserExperimentVariant(
            featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT]
        )

    switch (variant) {
        case 'simple':
            return <SimpleVariant {...props} experimentVariant={variant} />
        case 'new':
            return <NewLayoutVariant {...props} experimentVariant={variant} />
        default:
            return <SimpleVariant {...props} experimentVariant="control" />
    }
}
