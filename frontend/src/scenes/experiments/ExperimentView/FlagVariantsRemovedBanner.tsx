import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { experimentLogic } from '../experimentLogic'

export function FlagVariantsRemovedBanner(): JSX.Element {
    const { flagVariantsRemovedAt } = useValues(experimentLogic)

    return (
        <LemonBanner type="error">
            <p className="font-semibold mb-1">This experiment's feature flag no longer has variants</p>
            <p className="mb-0">
                The flag was changed from a multivariate flag to a boolean or rollout flag
                {flagVariantsRemovedAt ? ` on ${dayjs(flagVariantsRemovedAt).format('MMMM D, YYYY [at] h:mm A')}` : ''},
                so exposures and metrics can't be computed. Restore the flag's variants, or delete this experiment, to
                see results again.
            </p>
        </LemonBanner>
    )
}
