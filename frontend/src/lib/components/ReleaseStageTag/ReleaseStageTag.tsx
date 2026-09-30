import { useValues } from 'kea'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { userLogic } from 'scenes/userLogic'

import { ReleaseStage, ReleaseStageProduct, releaseStage } from './releaseStage'

// PostHog's own feature flags live in this project, for every region.
const POSTHOG_PROJECT_URL = 'https://us.posthog.com/project/2'

const TAG_TYPES: Record<ReleaseStage, LemonTagType> = {
    alpha: 'completion',
    beta: 'warning',
    internal: 'highlight',
}

const DESCRIPTIONS: Record<ReleaseStage, string> = {
    alpha: 'This is an early version. It can change a lot.',
    beta: 'This is almost ready. Some parts can still change.',
    internal: 'This is not released to customers yet.',
}

/** Shows if a product is in alpha, in beta, or internal only. Staff see who can use it. */
export function ReleaseStageTag({
    product,
    className,
}: {
    product: ReleaseStageProduct
    className?: string
}): JSX.Element | null {
    const { user } = useValues(userLogic)
    const stage = releaseStage(product)
    if (!stage) {
        return null
    }

    const tag = (
        <LemonTag type={TAG_TYPES[stage]} size="small" className={className}>
            {stage}
        </LemonTag>
    )
    if (!user?.is_staff) {
        return tag
    }

    return (
        <Tooltip
            interactive
            title={
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
            }
        >
            {tag}
        </Tooltip>
    )
}
