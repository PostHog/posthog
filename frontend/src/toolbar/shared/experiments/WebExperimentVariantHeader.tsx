import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'

interface WebExperimentVariantHeaderProps {
    variant: string
}

export function WebExperimentVariantHeader({ variant }: WebExperimentVariantHeaderProps): JSX.Element {
    const { variants, removeVariantAvailable, selectedVariant, removeVariant } = useWebExperimentEditor()
    return (
        <div className="flex w-full items-center justify-between">
            <div className="flex items-center gap-2">
                <h2>{variant}</h2>
                {selectedVariant === variant && (
                    <LemonTag className="px-1 py-0.5 font-semibold" size="small" type="success">
                        Currently applied
                    </LemonTag>
                )}
            </div>
            <div className="flex items-center gap-2">
                <LemonTag className="px-1 py-0.5 font-semibold" size="small" type="muted">
                    <span>{`Rollout: ${variants[variant]?.rollout_percentage ?? 0} %`}</span>
                </LemonTag>
                {removeVariantAvailable && variant !== 'control' && (
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
            </div>
        </div>
    )
}
