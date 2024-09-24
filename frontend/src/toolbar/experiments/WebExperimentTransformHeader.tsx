import { IconTarget, IconTrash } from '@posthog/icons'
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
    const { inspectingElement, selectedVariant } = useValues(experimentsTabLogic)
    const { removeElement, inspectForElementWithIndex, selectVariant } = useActions(experimentsTabLogic)

    return (
        <div className="flex w-full gap-4 items-center">
            <div className="flex-1">
                <LemonButton
                    size="small"
                    type={inspectingElement === transformIndex && selectedVariant === variant ? 'primary' : 'secondary'}
                    onClick={(e) => {
                        e.stopPropagation()
                        selectVariant(variant)
                        inspectForElementWithIndex(
                            variant,
                            inspectingElement === transformIndex ? null : transformIndex
                        )
                    }}
                    icon={<IconTarget />}
                >
                    {transform.selector || 'Please select an element'}
                </LemonButton>
            </div>

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
        </div>
    )
}
