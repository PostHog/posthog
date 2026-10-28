import { IconCursorClick } from '@posthog/icons'
import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { ElementSelectorButtonTypes, ElementSelectorType } from '~/toolbar/shared/experiments/elementSelectorTypes'
import { htmlSanitizationWouldStrip, styleSanitizationWouldStrip } from '~/toolbar/shared/experiments/sanitize'
import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'
import { WebExperimentTransform } from '~/toolbar/shared/types'

interface WebExperimentTransformFieldProps {
    variant: string
    transformIndex: number
    transform: WebExperimentTransform
}

export function WebExperimentTransformField({
    variant,
    transformIndex,
    transform,
}: WebExperimentTransformFieldProps): JSX.Element {
    const {
        inspectingElement,
        selectedVariant,
        selectedElementType,
        selectElementType,
        inspectForTransformation,
        setTransformationField,
    } = useWebExperimentEditor()
    const isInspecting = inspectingElement === transformIndex && selectedVariant === variant

    return (
        <>
            <div className="inline-flex deprecated-space-x-2">
                <LemonButton
                    icon={<IconCursorClick />}
                    size="small"
                    type={isInspecting ? 'primary' : 'secondary'}
                    onClick={() => inspectForTransformation(variant, isInspecting ? null : transformIndex)}
                >
                    {isInspecting ? 'Selecting…' : 'Select element'}
                </LemonButton>
                <LemonSelect
                    placeholder="Select element type"
                    value={selectedElementType}
                    options={Object.entries(ElementSelectorButtonTypes).map(([key, value]) => ({
                        label: value,
                        value: key,
                    }))}
                    onChange={(value) => {
                        selectElementType(value as ElementSelectorType)
                    }}
                />
            </div>
            {transform.selector && (
                <div>
                    <div className="mt-4">
                        <LemonLabel>Inner HTML</LemonLabel>
                        <LemonTextArea
                            onChange={(value) => setTransformationField(variant, transformIndex, 'html', value)}
                            value={transform.html}
                            maxRows={8}
                        />
                        {htmlSanitizationWouldStrip(transform.html) && (
                            <div className="text-xs text-secondary mt-1">
                                Some markup will be removed when applied (scripts, event handlers, inline styles).
                            </div>
                        )}
                    </div>
                    <div className="mt-4">
                        <LemonLabel>CSS</LemonLabel>
                        <LemonTextArea
                            onChange={(value) => setTransformationField(variant, transformIndex, 'css', value)}
                            value={transform.css || ''}
                            maxRows={8}
                        />
                        {styleSanitizationWouldStrip(transform.css) && (
                            <div className="text-xs text-secondary mt-1">
                                Some declarations will be removed when applied (url(), image-set, paint).
                            </div>
                        )}
                    </div>
                </div>
            )}
        </>
    )
}
