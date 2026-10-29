import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonLabel } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'
import { WebExperimentTransformField } from '~/toolbar/shared/experiments/WebExperimentTransformField'
import { WebExperimentTransformHeader } from '~/toolbar/shared/experiments/WebExperimentTransformHeader'

interface WebExperimentVariantProps {
    variant: string
}

export function WebExperimentVariant({ variant }: WebExperimentVariantProps): JSX.Element {
    const { variants, selectedExperimentId, renameVariant, addTransformation } = useWebExperimentEditor()
    const [localTentativeValue, setLocalTentativeValue] = useState(variant)
    const transforms = variants[variant]?.transforms ?? []
    return (
        <div className="deprecated-space-y-4">
            {selectedExperimentId === 'new' && variants[variant]?.is_new && (
                <div>
                    <LemonLabel>Variant key</LemonLabel>
                    <LemonInput
                        key="variant-name-small"
                        className="mb-2"
                        value={localTentativeValue}
                        onChange={(newName) => {
                            setLocalTentativeValue(newName)
                        }}
                        onBlur={(e) => {
                            e.stopPropagation()
                            if (localTentativeValue !== variant && !renameVariant(variant, localTentativeValue)) {
                                setLocalTentativeValue(variant)
                            }
                        }}
                        placeholder='Example: "test-1"'
                    />
                </div>
            )}
            <div className="flex items-center justify-between mb-2">
                <LemonLabel>Transformations</LemonLabel>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconPlus />}
                    onClick={(e) => {
                        e.stopPropagation()
                        addTransformation(variant)
                    }}
                >
                    Add transformation
                </LemonButton>
            </div>
            {transforms.length > 0 ? (
                <LemonCollapse
                    size="small"
                    defaultActiveKey={transforms.length === 1 ? 0 : undefined}
                    panels={transforms.map((transform, transformIndex) => {
                        return {
                            key: transformIndex,
                            header: (
                                <WebExperimentTransformHeader
                                    variant={variant}
                                    transformIndex={transformIndex}
                                    transform={transform}
                                />
                            ),
                            content: (
                                <WebExperimentTransformField
                                    transformIndex={transformIndex}
                                    variant={variant}
                                    transform={transform}
                                />
                            ),
                        }
                    })}
                />
            ) : (
                <span className="my-2"> This experiment variant doesn't modify any elements. </span>
            )}
        </div>
    )
}
