import { JSONContent } from '@tiptap/core'
import { renderProductTourPreview } from 'posthog-js/dist/product-tours-preview'
import { useEffect, useRef } from 'react'

import { ProductTourAppearance, ProductTourStep } from '~/types'

import { StepContentEditor } from './editor/StepContentEditor'
import { StepLayoutSettings } from './editor/StepLayoutSettings'
import { prepareStepForRender } from './editor/generateStepHtml'

export interface AnnouncementContentEditorProps {
    step: ProductTourStep | undefined
    appearance: ProductTourAppearance | undefined
    onChange: (step: ProductTourStep) => void
}

export function AnnouncementContentEditor({ step, appearance, onChange }: AnnouncementContentEditorProps): JSX.Element {
    const previewRef = useRef<HTMLDivElement>(null)

    const updateStep = (updates: Partial<ProductTourStep>): void => {
        if (step) {
            onChange({ ...step, ...updates })
        }
    }

    useEffect(() => {
        if (previewRef.current && step) {
            renderProductTourPreview({
                step: prepareStepForRender(step) as any,
                appearance: appearance as any,
                parentElement: previewRef.current,
                stepIndex: 0,
                totalSteps: 1,
            })
        }
    }, [step, step?.maxWidth, appearance])

    if (!step) {
        return <div>No content</div>
    }

    return (
        <div className="flex gap-8 items-start">
            <div className="flex-1 min-w-0">
                <StepContentEditor
                    content={step.content as JSONContent | null}
                    onChange={(content) => updateStep({ content })}
                    placeholder="Type '/' for commands, or start writing your announcement..."
                />

                <div className="mt-6 pt-6 border-t">
                    <StepLayoutSettings step={step} onChange={updateStep} />
                </div>
            </div>

            <div className="flex-1 min-w-0 sticky top-4">
                <div className="text-xs text-muted uppercase tracking-wide mb-3">Preview</div>
                <div className="flex justify-center items-center p-8 bg-[#f0f0f0] rounded min-h-[300px]">
                    <div ref={previewRef} />
                </div>
            </div>
        </div>
    )
}
