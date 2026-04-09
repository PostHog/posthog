import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'

import { DashboardTemplateType, TemplateAvailabilityContext } from '~/types'

import BlankDashboardHog from 'public/blank-dashboard-hog.png'

import {
    dashboardTemplateChooserLogic,
    DashboardTemplateChooserExperimentVariant,
    DashboardTemplateChooserLogicProps,
} from './dashboardTemplateChooserLogic'
import { TemplateItem } from './DashboardTemplateItem'
import { DashboardTemplateItemSkeleton } from './DashboardTemplateItemSkeleton'
import { DashboardTemplateProps } from './dashboardTemplatesLogic'

export type { DashboardTemplateChooserExperimentVariant } from './dashboardTemplateChooserLogic'

const gridClass = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4'

/** Single column on small viewports; two columns from `lg` up (modal/tablet often still feels “small” at `md`) */
const featuredGridClass = 'grid grid-cols-1 lg:grid-cols-2 gap-4'

function filterTemplatesByAvailability(
    allTemplates: DashboardTemplateType[],
    availabilityContexts: DashboardTemplateProps['availabilityContexts']
): DashboardTemplateType[] {
    if (!availabilityContexts?.length) {
        return allTemplates
    }
    return allTemplates.filter((template) =>
        availabilityContexts.some((context: TemplateAvailabilityContext) =>
            template.availability_contexts?.includes(context)
        )
    )
}

function computeShowBlankTile(availabilityContexts: DashboardTemplateProps['availabilityContexts']): boolean {
    return (
        !availabilityContexts ||
        availabilityContexts.length === 0 ||
        availabilityContexts.includes(TemplateAvailabilityContext.GENERAL)
    )
}

function SimpleVariant(
    props: DashboardTemplateProps & { experimentVariant: DashboardTemplateChooserExperimentVariant }
): JSX.Element {
    const { experimentVariant, className, availabilityContexts, ...chooserProps } = props
    const logicProps: DashboardTemplateChooserLogicProps = { ...chooserProps, experimentVariant, availabilityContexts }
    const chooser = dashboardTemplateChooserLogic(logicProps)
    const { allTemplates, allTemplatesLoading } = useValues(chooser)
    const { templateTileClicked, blankTileClicked } = useActions(chooser)
    const filteredTemplates = useMemo(
        () => filterTemplatesByAvailability(allTemplates, availabilityContexts),
        [allTemplates, availabilityContexts]
    )
    const showBlankTile = computeShowBlankTile(availabilityContexts)

    return (
        <div className={cn(gridClass, className)}>
            {showBlankTile ? (
                <TemplateItem
                    template={{
                        template_name: 'Blank dashboard',
                        dashboard_description: 'Create a blank dashboard',
                        image_url: BlankDashboardHog,
                        tags: [],
                    }}
                    onClick={() => blankTileClicked('main_grid')}
                    index={0}
                    data-attr="create-dashboard-blank"
                />
            ) : null}
            {allTemplatesLoading
                ? Array.from({ length: 3 }).map((_, i) => <DashboardTemplateItemSkeleton key={i} />)
                : filteredTemplates.map((template, index) => (
                      <TemplateItem
                          key={template.id}
                          template={template}
                          onClick={() => templateTileClicked(template, 'main_grid')}
                          index={index + 1}
                          data-attr="create-dashboard-from-template"
                          showFavourite={experimentVariant === 'simple' && template.is_featured}
                      />
                  ))}
        </div>
    )
}

function NewLayoutVariant(
    props: DashboardTemplateProps & { experimentVariant: DashboardTemplateChooserExperimentVariant }
): JSX.Element {
    const { experimentVariant, className, availabilityContexts, ...chooserProps } = props
    const logicProps: DashboardTemplateChooserLogicProps = { ...chooserProps, experimentVariant, availabilityContexts }
    const chooser = dashboardTemplateChooserLogic(logicProps)
    const { allTemplates, allTemplatesLoading, templateFilter } = useValues(chooser)
    const { templateTileClicked, blankTileClicked, setTemplateFilter } = useActions(chooser)
    const filteredTemplates = useMemo(
        () => filterTemplatesByAvailability(allTemplates, availabilityContexts),
        [allTemplates, availabilityContexts]
    )
    const showBlankTile = computeShowBlankTile(availabilityContexts)

    const featuredTemplates = useMemo(
        () => filteredTemplates.filter((t) => t.is_featured === true),
        [filteredTemplates]
    )
    const nonFeaturedTemplates = useMemo(
        () => filteredTemplates.filter((t) => t.is_featured !== true),
        [filteredTemplates]
    )

    const hasActiveFilter = templateFilter.trim().length > 0
    /** No non-featured rows — but if Popular still has cards, don’t show the “no templates” dashed panel */
    const showDashedEmptyState =
        !allTemplatesLoading && nonFeaturedTemplates.length === 0 && featuredTemplates.length === 0
    /** All matching templates are in Popular; bottom grid stays empty of templates */
    const allMatchesInFeaturedSection = nonFeaturedTemplates.length === 0 && featuredTemplates.length > 0

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

            <section>
                <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                        <h3 className="text-base font-semibold m-0">All templates</h3>
                        <p className="text-secondary text-sm m-0 mt-1">
                            Start from scratch or pick any template below.
                        </p>
                    </div>
                    {showBlankTile && !showDashedEmptyState && !allMatchesInFeaturedSection ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() => blankTileClicked('main_grid')}
                            data-attr="create-dashboard-blank"
                            className="shrink-0 self-end sm:mt-0.5"
                        >
                            Start from scratch
                        </LemonButton>
                    ) : null}
                </div>
                <div className={gridClass}>
                    {allTemplatesLoading ? (
                        <>
                            {Array.from({ length: 3 }).map((_, i) => (
                                <DashboardTemplateItemSkeleton key={i} />
                            ))}
                        </>
                    ) : showDashedEmptyState ? (
                        <div className="col-span-full flex flex-col items-center justify-center rounded-md border border-dashed border-border bg-fill-secondary px-6 py-14 text-center">
                            <h4 className="m-0 text-base font-semibold">
                                {hasActiveFilter ? 'No templates match your search' : 'No templates to show here'}
                            </h4>
                            <p className="mt-2 mb-0 max-w-md text-secondary text-sm">
                                {hasActiveFilter
                                    ? 'Try different keywords, clear the filter to see all templates again, or start with a blank dashboard.'
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
                                        data-attr="create-dashboard-blank"
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
                    ) : allMatchesInFeaturedSection && showBlankTile ? (
                        <TemplateItem
                            template={{
                                template_name: 'Blank dashboard',
                                dashboard_description: 'Create a blank dashboard',
                                image_url: BlankDashboardHog,
                                tags: [],
                            }}
                            onClick={() => blankTileClicked('main_grid')}
                            index={0}
                            data-attr="create-dashboard-blank"
                        />
                    ) : allMatchesInFeaturedSection ? (
                        <p className="col-span-full m-0 text-center text-secondary text-sm py-2">
                            Every template that matches is in Popular above.
                        </p>
                    ) : (
                        nonFeaturedTemplates.map((template, index) => (
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
        </div>
    )
}

export function DashboardTemplateChooser(props: DashboardTemplateProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const v = featureFlags[FEATURE_FLAGS.DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT]
    const variant: DashboardTemplateChooserExperimentVariant =
        v === 'simple' || v === 'new' || v === 'control' ? v : 'new'

    switch (variant) {
        case 'simple':
            return <SimpleVariant {...props} experimentVariant={variant} />
        case 'new':
            return <NewLayoutVariant {...props} experimentVariant={variant} />
        case 'control':
            return <SimpleVariant {...props} experimentVariant="control" />
    }
}
