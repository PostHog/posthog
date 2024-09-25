import { IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransform } from '~/toolbar/types'

interface WebExperimentTransformHeaderProps {
    variant: string
    transformIndex: number
    transform: WebExperimentTransform
}

export function WebExperimentTransformHeader({
    variant,
    transformIndex,
    transform,
}: WebExperimentTransformHeaderProps): JSX.Element {
    const { removeElement } = useActions(experimentsTabLogic)
    const { experimentForm } = useValues(experimentsTabLogic)

    return (
        <div className="flex w-full gap-4 items-center">
            <div className="flex-1">
                <h2>{transform.selector || 'Select element'}</h2>
            </div>
            {/*Only show the remove button if there's more than one transform*/}
            {experimentForm?.variants && experimentForm.variants[variant].transforms.length > 1 && (
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    className="shrink"
                    noPadding
                    status="danger"
                    onClick={(e) => {
                        e.stopPropagation()
                        removeElement(variant, transformIndex)
                    }}
                />
            )}
        </div>
    )
}
