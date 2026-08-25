import { Link } from '@posthog/lemon-ui'

export const COHORT_BEHAVIORAL_LIMITATIONS_URL =
    'https://posthog.com/docs/feature-flags/common-questions#why-cant-i-use-a-cohort-with-behavioral-filters-in-my-feature-flag'

export const EARLY_ACCESS_GROUP_TARGETING_DISABLED_REASON =
    'This flag is linked to an early access feature, so it can only target users. Remove the early access feature to target groups.'

export const MATCHING_ESTIMATE_TOOLTIP = (
    <>
        <div>
            A user may have{' '}
            <Link to="https://posthog.com/docs/data/persons#duplicate-person-profiles" target="_blank">
                multiple profiles
            </Link>
        </div>
        <div className="mt-1">
            Estimated from{' '}
            <Link to="https://posthog.com/docs/data/anonymous-vs-identified-events" target="_blank">
                identified users
            </Link>{' '}
            only. Anonymous visitors can still match this flag, so the actual number may be higher.
        </div>
    </>
)
