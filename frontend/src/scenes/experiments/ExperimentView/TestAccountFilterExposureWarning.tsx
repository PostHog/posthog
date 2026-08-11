import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { experimentLogic } from '../experimentLogic'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

/**
 * Surfaces the most common reason an experiment shows zero exposures during setup: the
 * test-account filter is on and the project has test-account filters configured, so the
 * person testing their own flag is dropped from exposures while the flag still fires
 * events. The backend only sets `test_account_filter_hiding_exposures` when all three
 * conditions hold, so presence of the flag is the gate.
 */
export function TestAccountFilterExposureWarning(): JSX.Element | null {
    const { exposures, exposureCriteria } = useValues(experimentLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)

    if (!exposures?.test_account_filter_hiding_exposures) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="flex-1 min-w-[300px]">
                    <div className="font-semibold">Test account filtering may be hiding your exposures</div>
                    <p className="m-0">
                        This experiment has no exposures yet, but its exposure criteria filters out internal and test
                        users. If your own traffic matches the project's{' '}
                        <Link to={urls.settings('environment-customization', 'internal-user-filtering')}>
                            test-account filters
                        </Link>
                        , such as your email domain, your exposures are dropped even though the flag still evaluates and
                        still fires events.
                    </p>
                    <p className="m-0 mt-1">
                        Turn off <strong>Filter out internal and test users</strong> in the exposure criteria to
                        confirm, or adjust the filters so they don't match your test traffic.
                    </p>
                </div>
                <div className="flex gap-2 items-center flex-shrink-0">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => openExposureCriteriaModal(exposureCriteria)}
                    >
                        Edit exposure criteria
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
