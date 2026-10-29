import { IconTrash } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { SelectorCount } from '~/toolbar/shared/actions/SelectorCount'
import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'
import { WebExperimentTransform } from '~/toolbar/shared/types'

import { SelectorEditor } from './SelectorEditor'

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
    const { removeTransformation } = useWebExperimentEditor()

    return (
        <div className="flex w-full gap-4 items-center">
            <div className="flex-1 overflow-hidden">
                {transform.selector ? (
                    <Tooltip title={transform.selector}>
                        <span className="max-w-[290px] truncate inline-block">{transform.selector}</span>
                    </Tooltip>
                ) : (
                    <span className="text-muted italic">No element selected</span>
                )}
            </div>

            {transform.selector && (
                <div className="float-right flex items-center gap-2">
                    <SelectorCount selector={transform.selector} />
                    <SelectorEditor selector={transform.selector} variant={variant} transformIndex={transformIndex} />
                </div>
            )}

            <LemonButton
                icon={<IconTrash />}
                size="small"
                className="shrink"
                noPadding
                status="danger"
                tooltip="Remove transformation"
                onClick={(e) => {
                    e.stopPropagation()
                    removeTransformation(variant, transformIndex)
                }}
            />
        </div>
    )
}
