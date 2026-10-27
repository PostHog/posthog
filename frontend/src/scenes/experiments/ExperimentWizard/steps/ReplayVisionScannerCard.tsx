import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconEye } from '@posthog/icons'
import { LemonCard, LemonSwitch } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { VisionDocsLink } from 'products/replay_vision/frontend/components/DocsLink'

import type { ReplayVisionScannerOptionProps } from './types'

const HedgehogXRay = pngHoggie(xRayPng)

export function ReplayVisionScannerCard({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
}: ReplayVisionScannerOptionProps): JSX.Element {
    const title = 'Compare what users do in each variant'

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
                            Replay vision summarizes the recordings of people in this experiment and shows each variant
                            side by side.
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
                    It turns on when you launch the experiment and stops when the experiment ends. Each scanned session
                    costs {sessionPrice}.
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
