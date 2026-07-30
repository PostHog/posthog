import { renderProductTourPreview } from 'posthog-js/dist/product-tours-preview'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { ProductTourAppearance, ProductTourStep } from '~/types'

import { prepareStepForRenderStrict } from '../editor/generateStepHtml'

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
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        const container = ref.current
        if (!container) {
            return
        }

        try {
            renderProductTourPreview({
                step: (prepareStep ? prepareStepForRenderStrict(step) : step) as any,
                appearance: { ...appearance, zIndex: 1 } as any,
                parentElement: container,
                stepIndex,
                totalSteps,
            })
            setError(null)
        } catch (e) {
            // A half-rendered step is worse than none, and the SDK renders into `container` directly.
            container.innerHTML = ''
            setError(e instanceof Error ? e.message : String(e))
        }

        return () => {
            container.innerHTML = ''
        }
    }, [step, appearance, stepIndex, totalSteps, prepareStep])

    return (
        <>
            {error && (
                <LemonBanner type="error" className="w-full">
                    <p className="font-semibold mb-1">This step can't be previewed</p>
                    <p className="mb-0">
                        Part of the step content failed to render, so it probably won't show up on your site either. Try
                        undoing your last change to the content. Error: {error}
                    </p>
                </LemonBanner>
            )}
            <div ref={ref} className={error ? 'hidden' : undefined} />
        </>
    )
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
            <div className="bg-[#f0f0f0] overflow-hidden p-4 -m-4">
                {step && <ProductTourPreview step={step} appearance={appearance} />}
            </div>
        </div>
    )
}
