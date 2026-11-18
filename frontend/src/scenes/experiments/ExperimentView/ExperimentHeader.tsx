import { useValues } from 'kea'

import { Card, CardContent } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import {
    QuillExperimentImplementationDetails,
    QuillWebExperimentImplementationDetails,
} from '../QuillExperimentImplementationDetails'
import { WebExperimentImplementationDetails } from '../WebExperimentImplementationDetails'

export function ExperimentHeader(): JSX.Element {
    const { experiment, isExperimentLaunched } = useValues(experimentLogic)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav && resultsRedesign) {
        return isExperimentLaunched ? (
            <></>
        ) : (
            <Card size="sm" data-attr="experiment-draft-implementation">
                <CardContent>
                    {experiment.type === 'web' ? (
                        <QuillWebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <QuillExperimentImplementationDetails experiment={experiment} placement="draft_header" />
                    )}
                </CardContent>
            </Card>
        )
    }

    return (
        <>
            {!isExperimentLaunched && (
                <div className="border rounded bg-surface-primary p-4">
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} placement="draft_header" />
                    )}
                </div>
            )}
        </>
    )
}
