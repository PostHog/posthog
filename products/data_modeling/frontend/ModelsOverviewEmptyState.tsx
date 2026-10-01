import * as float from '@posthog/brand/hoggies/png/float'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const HedgehogFloat = pngHoggie(float)

export type ModelsOverviewChecksStatus = 'disabled' | 'unknown' | 'none' | 'all-passed' | 'some-not-passed'

const HEALTHY_DESCRIPTIONS: Record<ModelsOverviewChecksStatus, string> = {
    disabled: 'Your models are up to date.',
    unknown: 'Your models are up to date.',
    none: 'Your models are up to date. Add data quality checks to test your data.',
    'all-passed': 'Your models are up to date and all data quality checks passed.',
    'some-not-passed': 'Your models are up to date. No checks are failing, but some have not passed yet.',
}

export interface ModelsOverviewEmptyStateProps {
    variant: 'healthy' | 'first-view'
    checksStatus: ModelsOverviewChecksStatus
}

export function ModelsOverviewEmptyState({ variant, checksStatus }: ModelsOverviewEmptyStateProps): JSX.Element {
    const firstView = variant === 'first-view'

    return (
        <div data-attr={firstView ? 'models-overview-first-view' : 'models-overview-healthy'}>
            <ProductIntroduction
                thingName="model"
                titleOverride={firstView ? 'Create your first view' : 'No models need attention'}
                description={
                    firstView
                        ? 'Save a SQL query as a view to start building your models.'
                        : HEALTHY_DESCRIPTIONS[checksStatus]
                }
                customHog={HedgehogFloat}
                hogLayout="responsive"
                useMainContentContainerQueries
                className="border border-solid bg-surface-primary my-0"
                actionElementOverride={
                    <>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.WarehouseObjects}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                to={urls.sqlEditor({ source: 'view' })}
                                data-attr="models-overview-create-view"
                            >
                                Create view
                            </LemonButton>
                        </AccessControlAction>
                        {checksStatus !== 'disabled' && (
                            <LemonButton
                                type="secondary"
                                to={urls.models('data-quality')}
                                data-attr="models-overview-checks"
                            >
                                {checksStatus === 'none' ? 'Set up checks' : 'View checks'}
                            </LemonButton>
                        )}
                        {!firstView && (
                            <LemonButton
                                type="secondary"
                                to={urls.models('lineage')}
                                data-attr="models-overview-lineage"
                            >
                                View lineage
                            </LemonButton>
                        )}
                    </>
                }
            />
        </div>
    )
}
