import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getEventPropertiesForExperiment } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import type { Experiment } from '~/types'

import { healthFindingForExperimentWarning } from 'products/experiments/frontend/health/experimentHealthFindingEvents'
import { useHealthFindingReporting } from 'products/experiments/frontend/health/useHealthFindingReporting'

import { experimentLogic } from '../experimentLogic'
import { WarningDetail, warningCaption } from './ExperimentWarningDetail'
import { QuillExperimentWarningBanner } from './QuillExperimentWarningBanner'

function reportExperimentInconsistencyWarningShown(experiment: Experiment, warningKey: string): void {
    posthog.capture('experiment inconsistency warning shown', {
        ...getEventPropertiesForExperiment(experiment),
        warning_key: warningKey,
    })
}

export function ExperimentWarningBanner(): JSX.Element | null {
    const { experimentWarning, experiment } = useValues(experimentLogic)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const quill = todayRailNav && resultsRedesign
    const { reportActedOn } = useHealthFindingReporting(
        experimentWarning ? healthFindingForExperimentWarning(experimentWarning.key) : null
    )

    useEffect(() => {
        if (experimentWarning) {
            reportExperimentInconsistencyWarningShown(experiment, experimentWarning.key)
        }
    }, [experimentWarning, experiment])

    if (!experimentWarning) {
        return null
    }

    if (quill) {
        return (
            <QuillExperimentWarningBanner
                warning={experimentWarning}
                flag={experiment.feature_flag ?? null}
                onOpenFlag={() => reportActedOn('open_feature_flag')}
            />
        )
    }

    const flagLink = experiment.feature_flag ? (
        <Link
            target="_blank"
            to={urls.featureFlag(experiment.feature_flag.id)}
            onClick={() => reportActedOn('open_feature_flag')}
        >
            {experiment.feature_flag.key}
        </Link>
    ) : null

    return (
        <LemonBanner className="mb-4" type="warning">
            <div>
                <strong>{warningCaption(experimentWarning.key)}</strong>
            </div>
            <div>
                <WarningDetail warning={experimentWarning} flagLink={flagLink} />
            </div>
        </LemonBanner>
    )
}
