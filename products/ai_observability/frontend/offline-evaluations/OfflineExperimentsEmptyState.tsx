import * as robotPng from '@posthog/brand/hoggies/png/robot'
import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

const HedgehogRobot = pngHoggie(robotPng)

export function OfflineExperimentsEmptyState(): JSX.Element {
    return (
        <ProductIntroduction
            thingName="offline experiment"
            titleOverride="Set up your first offline experiment"
            description="Run evaluations in your own environment and upload the results to PostHog. Track score changes and inspect the answers behind them."
            customHog={HedgehogRobot}
            hogLayout="responsive"
            useMainContentContainerQueries
            hogClassName="hidden @min-[48rem]/main-content:block max-w-48"
            className="p-6 @min-[48rem]/main-content:p-8"
            actionElementOverride={
                <div className="space-y-6 text-left">
                    <ol className="list-decimal pl-5 space-y-3 mb-0 marker:text-muted">
                        <li className="pl-1">
                            <strong>Define your scorers.</strong> Choose numeric, boolean, or categorical scores for the
                            things you want to measure.
                        </li>
                        <li className="pl-1">
                            <strong>Run and upload an experiment.</strong> Send inputs, outputs, and scorer results
                            through the offline evaluations API.
                        </li>
                        <li className="pl-1">
                            <strong>Track changes over time.</strong> Choose the scores to follow, compare experiments,
                            and open individual results to investigate a regression.
                        </li>
                    </ol>
                    <LemonButton
                        type="primary"
                        className="w-fit mt-6"
                        to={urls.aiObservabilityScorers()}
                        sideIcon={<IconArrowRight />}
                        data-attr="offline-experiments-set-up-scorers"
                    >
                        Set up scorers
                    </LemonButton>
                </div>
            }
        />
    )
}
