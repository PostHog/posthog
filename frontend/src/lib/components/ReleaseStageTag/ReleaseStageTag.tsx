import { useValues } from 'kea'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { userLogic } from 'scenes/userLogic'

import { ReleaseStage, ReleaseStageProduct, releaseStage } from './releaseStage'
import { ReleaseStageDetails } from './ReleaseStageDetails'

const TAG_TYPES: Record<ReleaseStage, LemonTagType> = {
    alpha: 'completion',
    beta: 'warning',
    internal: 'highlight',
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
        <Tooltip interactive title={<ReleaseStageDetails stage={stage} product={product} />}>
            {tag}
        </Tooltip>
    )
}
