import { IconTarget } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransformField } from '~/toolbar/experiments/WebExperimentTransformField'
import { WebExperimentTransformHeader } from '~/toolbar/experiments/WebExperimentTransformHeader'

interface WebExperimentVariantProps {
    variant: string
}

export function WebExperimentVariant({ variant }: WebExperimentVariantProps): JSX.Element {
    const { experimentForm } = useValues(experimentsTabLogic)
    const { addNewElement } = useActions(experimentsTabLogic)
    return (
        <div className="flex flex-col">
            <LemonCollapse
                size="small"
                activeKey={0}
                panels={experimentForm.variants![variant].transforms.map((transform, tIndex) => {
                    return {
                        key: tIndex,
                        header: (
                            <WebExperimentTransformHeader
                                variant={variant}
                                transformIndex={tIndex}
                                transform={transform}
                            />
                        ),
                        content: (
                            <WebExperimentTransformField tIndex={tIndex} variant={variant} transform={transform} />
                        ),
                    }
                })}
            />

            <div className="grid grid-cols-3 gap-2 m-1">
                <LemonButton
                    icon={<IconTarget />}
                    type="secondary"
                    size="small"
                    className="col-span-1"
                    onClick={(e) => {
                        e.stopPropagation()
                        addNewElement(variant)
                    }}
                >
                    Add new
                </LemonButton>
                <div className="col-span-1" />
            </div>
        </div>
    )
}
