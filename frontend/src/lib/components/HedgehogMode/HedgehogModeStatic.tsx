import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { HedgehogConfig, MinimalHedgehogConfig } from '~/types'

export type HedgehogModeStaticProps = {
    size?: number | string
    config: HedgehogConfig | MinimalHedgehogConfig
    direction?: 'left' | 'right'
}

let staticHedgehogRenderer: any = null
let StaticHedgehogRendererClass: any = null
const CACHE = new Map<string, Promise<string | null>>()

// Lazy load the StaticHedgehogRenderer class
const getStaticHedgehogRenderer = async (): Promise<any> => {
    if (!staticHedgehogRenderer && typeof window !== 'undefined') {
        const module = await import('@posthog/hedgehog-mode')
        StaticHedgehogRendererClass = module.StaticHedgehogRenderer
        staticHedgehogRenderer = new StaticHedgehogRendererClass({
            assetsUrl: '/static/hedgehog-mode/',
        })
    }
    return staticHedgehogRenderer
}

const renderHedgehog = async (
    skin: HedgehogConfig['actor_options']['skin'],
    accessories: HedgehogConfig['actor_options']['accessories'],
    color: HedgehogConfig['actor_options']['color']
): Promise<string | null> => {
    const key = JSON.stringify({ skin, accessories, color })
    if (!CACHE.has(key)) {
        const promise = getStaticHedgehogRenderer()
            .then((renderer) =>
                renderer.render({
                    id: JSON.stringify({
                        skin,
                        accessories: accessories,
                        color: color,
                    }),
                    skin,
                    accessories,
                    color,
                })
            )
            .then((src: any) => src)
            .catch((e: any) => {
                console.error('Error rendering hedgehog', e)
                return null
            })

        CACHE.set(key, promise)
    }

    return CACHE.get(key)!
}

// Takes a range of options and renders a static hedgehog
export function HedgehogModeStatic({ config, size, direction = 'right' }: HedgehogModeStaticProps): JSX.Element | null {
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
        void renderHedgehog(skin, accessories, color).then((src) => setDataUrl(src))
    }, [skin, accessories, color])

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className={clsx('relative', direction === 'left' && '-scale-x-100')}
            style={{ width: imgSize, height: imgSize }}
        >
            {dataUrl ? (
                <img style={{ imageRendering: 'pixelated' }} src={dataUrl} width={imgSize} height={imgSize} />
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
            <div className="absolute top-0 left-0 w-full h-full transform translate-x-[-15%] scale-[1.8]">
                <HedgehogModeStatic config={config} size={size} />
            </div>
        </div>
    )
}
