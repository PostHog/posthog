import { StaticHedgehogRenderer } from '@posthog/hedgehog-mode'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { useEffect, useState } from 'react'

import { HedgehogConfig } from '~/types'

export type HedgehogModeStaticProps = Partial<HedgehogConfig> & { size?: number | string }

const staticHedgehogRenderer = new StaticHedgehogRenderer({
    assetsUrl: '/static/hedgehog-mode/',
})

// Takes a range of options and renders a static hedgehog
export function HedgehogModeStatic({
    accessories,
    color,
    size,
    skin = 'default',
}: HedgehogModeStaticProps): JSX.Element | null {
    const imgSize = size ?? 60

    const [dataUrl, setDataUrl] = useState<string | null>(null)

    useEffect(() => {
        void staticHedgehogRenderer
            .render({
                id: JSON.stringify({
                    skin,
                    accessories: accessories as any,
                    color: color as any,
                }),
                skin,
                accessories: accessories as any,
                color: color as any,
            })
            .then((src) => {
                setDataUrl(src)
            })
            .catch((e) => {
                console.error('Error rendering hedgehog', e)
            })
    }, [skin, accessories, color])

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="relative" style={{ width: imgSize, height: imgSize }}>
            {dataUrl ? (
                <img src={dataUrl} width={imgSize} height={imgSize} />
            ) : (
                <LemonSkeleton className="w-full h-full" />
            )}
            <div className="absolute inset-0 bg-background-primary/50" />
        </div>
    )
}

export function HedgehogModeProfile({ size, ...props }: HedgehogModeStaticProps): JSX.Element {
    return (
        <div
            className="relative overflow-hidden rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size,
                height: size,
            }}
        >
            <div className="absolute top-0 left-0 w-full h-full transform translate-x-[-3%] translate-y-[10%] scale-[1.8]">
                <HedgehogModeStatic {...props} size={size} />
            </div>
        </div>
    )
}
