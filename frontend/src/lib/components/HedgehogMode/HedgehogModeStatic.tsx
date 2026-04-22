import clsx from 'clsx'
import { useMemo } from 'react'

import { HedgehogActorOptions, StaticHedgehog } from '@posthog/hedgehog-mode'

import { HedgehogConfig, MinimalHedgehogConfig } from '~/types'

import { getHedgehogModeAssetsUrl } from './HedgehogMode'

export type HedgehogModeStaticProps = {
    size?: number | string
    config: HedgehogConfig | MinimalHedgehogConfig
    direction?: 'left' | 'right'
}

// Takes a range of options and renders a static hedgehog
export function HedgehogModeStatic({ config, size, direction = 'right' }: HedgehogModeStaticProps): JSX.Element | null {
    // TRICKY: The minimal version of the config on an org member has a smaller footprint so we need to parse the right ones here
    const actorOptions = useMemo((): HedgehogActorOptions => {
        if ('actor_options' in config) {
            return config.actor_options
        }
        return {
            id: JSON.stringify({ skin: config.skin, color: config.color, accessories: config.accessories }),
            skin: config.skin,
            color: config.color,
            accessories: config.accessories,
        }
    }, [config])

    return (
        <StaticHedgehog
            options={actorOptions}
            size={size}
            assetsUrl={getHedgehogModeAssetsUrl()}
            className={clsx('relative rendering-pixelated', direction === 'left' && '-scale-x-100')}
        />
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
                <HedgehogModeStatic config={config} size="100%" />
            </div>
        </div>
    )
}
