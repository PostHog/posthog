import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'
import vegaEmbed from 'vega-embed'

import { LemonBanner } from '@posthog/lemon-ui'

import { HogQLQueryResponse } from '~/queries/schema/schema-general'

import {
    GENERATED_VEGA_LITE_VIEW_ATTR,
    POSTHOG_RESULTS_DATASET,
    SQLVisualizationGenerationField,
    ValidatedVegaLiteSpec,
    buildVegaLiteDataRows,
} from '../../generatedVegaLiteUtils'

interface VegaView {
    data: (name: string, values: Record<string, unknown>[]) => VegaView
    runAsync: () => Promise<unknown>
    finalize: () => void
}

interface VegaEmbedResult {
    view: VegaView
}

export interface VegaLiteChartProps {
    response: HogQLQueryResponse
    spec: ValidatedVegaLiteSpec
    fields: SQLVisualizationGenerationField[]
    className?: string
    onRenderError?: (error: string) => void
}

export function VegaLiteChart({ response, spec, fields, className, onRenderError }: VegaLiteChartProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const [renderError, setRenderError] = useState<string | null>(null)
    const dataRows = useMemo(() => buildVegaLiteDataRows(response, fields), [response, fields])

    useEffect(() => {
        let cancelled = false
        let embedResult: VegaEmbedResult | null = null
        const container = containerRef.current

        if (!container) {
            return
        }

        setRenderError(null)
        container.replaceChildren()

        const renderChart = async (): Promise<void> => {
            try {
                const embedOptions = {
                    actions: false,
                    renderer: 'canvas',
                    loader: {
                        load: async (): Promise<string> => {
                            throw new Error('External Vega resource loading is disabled.')
                        },
                    },
                } as unknown as Parameters<typeof vegaEmbed>[2]

                embedResult = (await vegaEmbed(container, spec, embedOptions)) as unknown as VegaEmbedResult

                embedResult.view.data(POSTHOG_RESULTS_DATASET, dataRows)
                await embedResult.view.runAsync()

                if (cancelled) {
                    embedResult.view.finalize()
                }
            } catch (error) {
                const message = error instanceof Error ? error.message : 'Could not render the generated chart.'
                if (!cancelled) {
                    if (onRenderError) {
                        onRenderError(message)
                    } else {
                        setRenderError(message)
                    }
                }
            }
        }

        void renderChart()

        return () => {
            cancelled = true
            embedResult?.view.finalize()
        }
    }, [dataRows, onRenderError, spec])

    if (renderError) {
        return (
            <div className={clsx('flex flex-col gap-2 p-3', className)} data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}>
                <LemonBanner type="warning">Could not render the generated chart: {renderError}</LemonBanner>
                <div ref={containerRef} className="hidden" />
            </div>
        )
    }

    return (
        <div
            ref={containerRef}
            className={clsx('w-full min-h-80 p-3', className)}
            data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}
        />
    )
}
