import { StaticHedgehogRenderer } from '@posthog/hedgehog-mode'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { useEffect, useMemo, useState } from 'react'

import { HedgehogConfig, MinimalHedgehogConfig } from '~/types'

export type HedgehogModeStaticProps = {
    size?: number | string
    config: HedgehogConfig | MinimalHedgehogConfig
}

const staticHedgehogRenderer = new StaticHedgehogRenderer({
    assetsUrl: '/static/hedgehog-mode/',
})

// Takes a range of options and renders a static hedgehog
export function HedgehogModeStatic({ config, size }: HedgehogModeStaticProps): JSX.Element | null {
    const imgSize = size ?? 60
    const [dataUrl, setDataUrl] = useState<string | null>(null)

    // TRICKY: The minimal version of the config on an org member has a smaller footprint so we need to parse the right ones here
    const { skin, color, accessories } = useMemo(() => {
        if ('actor_options' in config) {
            return config.actor_options
        }
        return config
    }, [config])

    useEffect(() => {
        void staticHedgehogRenderer
            .render({
                id: JSON.stringify({
                    skin,
                    accessories: accessories,
                    color: color,
                }),
                skin,
                accessories,
                color,
            })
            .then((src) => setDataUrl(src))
            .catch((e) => console.error('Error rendering hedgehog', e))
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

export function HedgehogModeProfile({ size, config }: HedgehogModeStaticProps): JSX.Element {
    return (
        <div
            className="overflow-hidden relative rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size,
                height: size,
            }}
        >
            <div className="absolute top-0 left-0 w-full h-full transform translate-x-[-3%] translate-y-[10%] scale-[1.8]">
                <HedgehogModeStatic config={config} size={size} />
            </div>
        </div>
    )
}
