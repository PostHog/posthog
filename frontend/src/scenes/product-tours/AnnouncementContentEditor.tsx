import { JSONContent } from '@tiptap/core'

import { ProductTourAppearance, ProductTourStep } from '~/types'

import { ProductTourPreview } from './components/ProductTourPreview'
import { StepButtonsEditor } from './editor/StepButtonsEditor'
import { StepContentEditor } from './editor/StepContentEditor'
import { StepLayoutSettings } from './editor/StepLayoutSettings'

export interface AnnouncementContentEditorProps {
    step: ProductTourStep | undefined
    appearance: ProductTourAppearance | undefined
    onChange: (step: ProductTourStep) => void
}

export function AnnouncementContentEditor({ step, appearance, onChange }: AnnouncementContentEditorProps): JSX.Element {
    const updateStep = (updates: Partial<ProductTourStep>): void => {
        if (step) {
            onChange({ ...step, ...updates })
        }
    }

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
                    <label className="text-sm font-medium block mb-3">Buttons</label>
                    <StepButtonsEditor buttons={step.buttons} onChange={(buttons) => updateStep({ buttons })} />
                </div>

                <div className="mt-6 pt-6 border-t">
                    <StepLayoutSettings step={step} onChange={updateStep} />
                </div>
            </div>

            <div className="flex-1 min-w-0 sticky top-4">
                <div className="text-xs text-muted uppercase tracking-wide mb-3">Preview</div>
                <div className="flex justify-center items-center p-8 bg-[#f0f0f0] rounded min-h-[300px]">
                    <ProductTourPreview step={step} appearance={appearance} />
                </div>
            </div>
        </div>
    )
}
