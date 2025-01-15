import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { useState } from 'react'

import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransformField } from '~/toolbar/experiments/WebExperimentTransformField'
import { WebExperimentTransformHeader } from '~/toolbar/experiments/WebExperimentTransformHeader'

interface WebExperimentVariantProps {
    variant: string
}

export function WebExperimentVariant({ variant }: WebExperimentVariantProps): JSX.Element {
    const { experimentForm, selectedExperimentId } = useValues(experimentsTabLogic)
    const [localTentativeValue, setLocalTentativeValue] = useState(variant)
    const { addNewElement, setExperimentFormValue } = useActions(experimentsTabLogic)
    return (
        <div className="flex flex-col">
            {selectedExperimentId === 'new' && experimentForm.variants && experimentForm.variants[variant].is_new && (
                <LemonInput
                    key="variant-name-small"
                    className="mb-2"
                    value={localTentativeValue}
                    onChange={(newName) => {
                        setLocalTentativeValue(newName)
                    }}
                    onBlur={(e) => {
                        e.stopPropagation()
                        if (experimentForm.variants && localTentativeValue !== variant) {
                            const webVariant = experimentForm.variants[variant]
                            if (webVariant) {
                                experimentForm.variants[localTentativeValue] = webVariant
                                delete experimentForm.variants[variant]
                                setExperimentFormValue('variants', experimentForm.variants)
                            }
                        }
                    }}
                    placeholder="Variant name"
                />
            )}
            {experimentForm?.variants &&
            experimentForm?.variants[variant] &&
            experimentForm?.variants[variant].transforms &&
            experimentForm?.variants[variant].transforms?.length > 0 ? (
                <LemonCollapse
                    size="small"
                    activeKey={experimentForm?.variants[variant].transforms.length === 1 ? 0 : undefined}
                    panels={experimentForm?.variants[variant].transforms.map((transform, tIndex) => {
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
            ) : (
                <span className="m-2"> This experiment variant doesn't modify any elements. </span>
            )}

            <div className="grid grid-cols-3 gap-2 m-1">
                <LemonButton
                    icon={<IconPlus />}
                    type="secondary"
                    size="small"
                    className="col-span-1"
                    onClick={(e) => {
                        e.stopPropagation()
                        addNewElement(variant)
                    }}
                >
                    Add element
                </LemonButton>
                <div className="col-span-1" />
            </div>
        </div>
    )
}
