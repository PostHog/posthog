import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { CohortPopulationType, CohortType, SidePanelTab } from '~/types'

const SOURCE_LABELS: Record<CohortPopulationType['source'], string> = {
    list: 'people you added',
    query: 'a query',
    filters: 'matching criteria',
    feature_flag: 'a feature flag',
    reconcile: 'a repair of this cohort',
}

function progressSummary(population: CohortPopulationType): string | null {
    const { identifiers_total, identifiers_written } = population.progress
    if (identifiers_total == null) {
        return null
    }
    return `${identifiers_written.toLocaleString()} of ${identifiers_total.toLocaleString()} processed so far.`
}

export function CohortPopulationBanner({ cohort }: { cohort: CohortType }): JSX.Element | null {
    const { retryPopulationLoading, abandonPopulationLoading } = useValues(cohortEditLogic)
    const { retryPopulation, abandonPopulation } = useActions(cohortEditLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const population = cohort.population
    if (!cohort.is_static || !population) {
        return null
    }

    if (population.status === 'completed') {
        return population.source === 'reconcile' ? (
            <LemonBanner type="warning">
                Membership synchronization finished. This does not recover people missing from an earlier upload. Upload
                the original list if that import was incomplete.
            </LemonBanner>
        ) : null
    }
    const source = SOURCE_LABELS[population.source]
    const progress = progressSummary(population)
    const canAbandon = population.available_actions.includes('abandon')
    const recoveryLoading = retryPopulationLoading || abandonPopulationLoading
    const canRetry = population.available_actions.includes('retry')

    if (population.status === 'pending' || population.status === 'running') {
        return (
            <LemonBanner
                type="info"
                action={
                    canAbandon
                        ? {
                              onClick: () => abandonPopulation(),
                              children: 'Stop',
                              loading: abandonPopulationLoading,
                              disabledReason: recoveryLoading ? 'Stopping' : undefined,
                              'data-attr': 'cohort-population-abandon',
                          }
                        : undefined
                }
            >
                <div className="flex items-center gap-x-2">
                    <Spinner size="small" />
                    <span>
                        <strong>
                            {canAbandon
                                ? `Adding people from ${source}.`
                                : 'Stopping and synchronizing people already added.'}
                        </strong>{' '}
                        {progress ?? 'This can take a few minutes.'} The list below fills in as it goes.
                    </span>
                </div>
            </LemonBanner>
        )
    }

    if (population.status === 'retry_scheduled') {
        return (
            <LemonBanner
                type="warning"
                action={
                    canAbandon
                        ? {
                              onClick: () => abandonPopulation(),
                              children: 'Stop',
                              loading: abandonPopulationLoading,
                              disabledReason: recoveryLoading ? 'Stopping' : undefined,
                              'data-attr': 'cohort-population-abandon',
                          }
                        : undefined
                }
            >
                <h4 className="font-semibold mb-1">Adding people hit a problem, and will try again</h4>
                <p className="mb-0">
                    {population.error_message ?? 'Something went wrong while adding people to this cohort.'}{' '}
                    {progress ? `${progress} ` : ''}
                    Attempt {population.attempts} of {population.max_attempts}
                    {population.next_attempt_at ? (
                        <>
                            , next one <TZLabel time={population.next_attempt_at} />
                        </>
                    ) : null}
                    . People already added stay in the cohort.
                </p>
            </LemonBanner>
        )
    }

    if (population.status === 'abandoned') {
        return (
            <LemonBanner type="warning">
                <h4 className="font-semibold mb-1">Population stopped before completion</h4>
                <p className="mb-0">
                    Adding people from {source} was stopped before it finished. Some people may be missing.{' '}
                    {progress ?? ''} Create a new cohort or upload the list again to complete it.
                </p>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="error"
            action={
                canRetry
                    ? {
                          onClick: () => retryPopulation(),
                          children: 'Try again',
                          loading: retryPopulationLoading,
                          disabledReason: recoveryLoading ? 'Trying again' : undefined,
                          'data-attr': 'cohort-population-retry',
                      }
                    : undefined
            }
        >
            <h4 className="font-semibold mb-1">Couldn't finish adding people to this cohort</h4>
            <p className="mb-0">
                {population.error_message ?? 'Something went wrong while adding people to this cohort.'}{' '}
                {progress ? `${progress} People already added stay in the cohort. ` : ''}
                {canRetry
                    ? 'Trying again picks up where it stopped.'
                    : 'Stop this run before uploading again or creating a new cohort.'}{' '}
                If it keeps happening,{' '}
                <Link onClick={() => openSidePanel(SidePanelTab.Support, 'bug:cohorts::true')}>contact support</Link>.
            </p>
            {canAbandon && (
                <LemonButton
                    className="mt-2"
                    onClick={() => abandonPopulation()}
                    loading={abandonPopulationLoading}
                    disabledReason={recoveryLoading ? 'Recovery is in progress' : undefined}
                    data-attr="cohort-population-abandon"
                >
                    Stop
                </LemonButton>
            )}
        </LemonBanner>
    )
}
