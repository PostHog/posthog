import { IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'

interface WebExperimentVariantHeaderProps {
    variant: string
}

export function WebExperimentVariantHeader({ variant }: WebExperimentVariantHeaderProps): JSX.Element {
    const { experimentForm } = useValues(experimentsTabLogic)
    const { removeVariant } = useActions(experimentsTabLogic)
    return (
        <div className="flex w-full gap-4 items-center">
            <div className="flex-1">
                <h2>{variant}</h2>
            </div>
            <div className="shrink">
                <LemonTag className="p-2" type="success">
                    <span>
                        {'rollout :' +
                            (experimentForm.variants && experimentForm.variants[variant]
                                ? experimentForm.variants[variant].rollout_percentage!
                                : 0
                            ).toString()}
                    </span>
                </LemonTag>
            </div>

            {/*Only show the remove button if there's more than one test variant, and the variant is not control*/}
            {variant !== 'control' &&
            experimentForm?.variants &&
            Object.keys(experimentForm.variants || {}).length > 2 ? (
                <LemonButton
                    icon={<IconTrash />}
                    size="small"
                    className="shrink"
                    noPadding
                    status="danger"
                    onClick={(e) => {
                        e.stopPropagation()
                        removeVariant(variant)
                    }}
                />
            ) : (
                <span className="size-5 inline-block" />
            )}
        </div>
    )
}
