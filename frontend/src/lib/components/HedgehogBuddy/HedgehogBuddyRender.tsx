import { HedgehogConfig } from '~/types'

import { COLOR_TO_FILTER_MAP } from './hedgehogBuddyLogic'
import { baseSpriteAccessoriesPath, baseSpritePath, standardAccessories } from './sprites/sprites'

export type HedgehogBuddyStaticProps = Partial<HedgehogConfig> & { size?: number | string }

// Takes a range of options and renders a static hedgehog
export function HedgehogBuddyStatic({ accessories, color, size }: HedgehogBuddyStaticProps): JSX.Element {
    const imgSize = size ?? 60

    const accessoryInfos = accessories?.map((x) => standardAccessories[x])
    const filter = color ? COLOR_TO_FILTER_MAP[color] : null

    return (
        <div
            className="relative overflow-hidden pointer-events-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: imgSize,
                height: imgSize,
                margin: -2,
            }}
        >
            <img
                src={`${baseSpritePath()}/wave.png`}
                className="object-cover absolute inset-0 image-pixelated"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: '400%',
                    height: '400%',
                    filter: filter as any,
                }}
            />

            {accessoryInfos?.map((accessory, index) => (
                <img
                    key={index}
                    src={`${baseSpriteAccessoriesPath()}/${accessory.img}.png`}
                    className="object-cover absolute inset-0 image-pixelated"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: imgSize,
                        height: imgSize,
                        filter: filter as any,
                    }}
                />
            ))}
        </div>
    )
}

export function HedgehogBuddyProfile({ size, ...props }: HedgehogBuddyStaticProps): JSX.Element {
    return (
        <div
            className="relative rounded-full overflow-hidden bg-bg-light border"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size,
                height: size,
            }}
        >
            <div
                className="absolute top-0 left-0 w-full h-full"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    transform: 'translate(-3%, 10%) scale(1.8)',
                }}
            >
                <HedgehogBuddyStatic {...props} size={size} />
            </div>
        </div>
    )
}
