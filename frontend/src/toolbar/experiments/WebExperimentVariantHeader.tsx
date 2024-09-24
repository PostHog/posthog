import { IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

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
                <LemonBadge
                    className="p-2"
                    content={
                        'rollout :' +
                        (experimentForm.variants && experimentForm.variants[variant]
                            ? experimentForm.variants[variant].rollout_percentage!
                            : 0
                        ).toString()
                    }
                    size="medium"
                    status="success"
                />
            </div>

            {variant !== 'control' && (
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
            )}
            {variant === 'control' && <span className="size-5 inline-block" />}
        </div>
    )
}
