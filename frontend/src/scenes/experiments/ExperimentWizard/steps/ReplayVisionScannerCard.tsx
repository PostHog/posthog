import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconEye } from '@posthog/icons'
import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { VisionDocsLink } from 'products/replay_vision/frontend/components/DocsLink'

const HedgehogXRay = pngHoggie(xRayPng)

export interface ReplayVisionScannerOptionProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
    sessionPrice: string
    /** VISION_EXPERIMENT_SCANNER: the save path creates an experiment scanner that turns on at launch */
    experimentScanners: boolean
}

export function ReplayVisionScannerCard({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
    experimentScanners,
}: ReplayVisionScannerOptionProps): JSX.Element {
    const title = experimentScanners
        ? 'Compare what users do in each variant'
        : 'Watch participant behavior with Replay Vision'

    return (
        <LemonCard hoverEffect={false} className="@container flex items-start gap-4 p-4">
            <HedgehogXRay className="hidden @md:block w-20 shrink-0" />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <div className="flex items-center gap-1.5 font-semibold">
                            <IconEye
                                className="size-4 shrink-0"
                                style={{ color: 'var(--color-product-session-replay-light)' }}
                            />
                            {title}
                        </div>
                        <p className="m-0 mt-1 text-sm text-secondary">
                            {experimentScanners
                                ? 'Replay vision summarizes the recordings of people in this experiment and shows each variant side by side.'
                                : "AI watches the recordings of people in this experiment, so you don't have to. Every result is an event you can query, graph, and alert on."}
                        </p>
                    </div>
                    <LemonSwitch
                        checked={checked}
                        onChange={onChange}
                        disabledReason={disabledReason}
                        aria-label={title}
                        data-attr="experiment-create-replay-vision-scanner"
                    />
                </div>
                <p className="m-0 text-xs text-muted">
                    {experimentScanners
                        ? 'It turns on when you launch the experiment and stops when the experiment ends.'
                        : "It's created turned off, so nothing is scanned until you turn it on."}{' '}
                    Each scanned session costs {sessionPrice}.
                </p>
                <div className="text-sm">
                    <VisionDocsLink dataAttr="experiment-create-replay-vision-docs">
                        Learn more about Replay Vision
                    </VisionDocsLink>
                </div>
            </div>
        </LemonCard>
    )
}
