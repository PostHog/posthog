import { renderProductTourPreview } from 'posthog-js/dist/product-tours-preview'
import { useEffect, useRef } from 'react'

import { ProductTourAppearance, ProductTourStep } from '~/types'

import { prepareStepForRender } from '../editor/generateStepHtml'

export interface ProductTourPreviewProps {
    step: ProductTourStep
    appearance?: ProductTourAppearance
    stepIndex?: number
    totalSteps?: number
    prepareStep?: boolean
}

export function ProductTourPreview({
    step,
    appearance,
    stepIndex = 0,
    totalSteps = 1,
    prepareStep = true,
}: ProductTourPreviewProps): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (ref.current) {
            renderProductTourPreview({
                step: (prepareStep ? prepareStepForRender(step) : step) as any,
                appearance: appearance as any,
                parentElement: ref.current,
                stepIndex,
                totalSteps,
            })
        }
    }, [step, appearance, stepIndex, totalSteps, prepareStep])

    return <div ref={ref} />
}

export function BannerPreviewWrapper({
    step,
    appearance,
}: {
    step: ProductTourStep
    appearance?: ProductTourAppearance
}): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted uppercase tracking-wide mb-3">Preview</div>
            <div className="bg-[#f0f0f0] overflow-hidden">
                {step && <ProductTourPreview step={step} appearance={appearance} />}
            </div>
        </div>
    )
}
