import { Link } from 'lib/lemon-ui/Link'

import { ReleaseStage, ReleaseStageProduct } from './releaseStage'

// PostHog's own feature flags live in this project, for every region.
const POSTHOG_PROJECT_URL = 'https://us.posthog.com/project/2'

const DESCRIPTIONS: Record<ReleaseStage, string> = {
    alpha: 'This is an early version. It can change a lot.',
    beta: 'This is almost ready. Some parts can still change.',
    internal: 'This is not released to customers yet.',
}

/** What a release stage means, and for staff, which feature flag controls who sees the product. */
export function ReleaseStageDetails({
    stage,
    product,
}: {
    stage: ReleaseStage
    product: ReleaseStageProduct
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span>{DESCRIPTIONS[stage]}</span>
            {product.flag ? (
                <>
                    <span>
                        People need the <code>{product.flag}</code> feature flag to see it.
                    </span>
                    <Link
                        to={`${POSTHOG_PROJECT_URL}/feature_flags?search=${encodeURIComponent(product.flag)}`}
                        target="_blank"
                        data-attr="release-stage-tag-feature-flag"
                    >
                        Open the feature flag
                    </Link>
                </>
            ) : (
                <span>No feature flag controls who can see it.</span>
            )}
            <span>Access controls can also hide it.</span>
        </div>
    )
}
