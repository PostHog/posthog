import { HedgehogConfig } from '~/types'

import { COLOR_TO_FILTER_MAP } from './hedgehogBuddyLogic'
import { spriteAccessoryUrl, spriteUrl, standardAccessories } from './sprites/sprites'

export type HedgehogBuddyStaticProps = Partial<HedgehogConfig> & { size?: number | string }

// Takes a range of options and renders a static hedgehog
export function HedgehogBuddyStatic({
    accessories,
    color,
    size,
    skin = 'default',
}: HedgehogBuddyStaticProps): JSX.Element {
    const imgSize = size ?? 60

    const accessoryInfos = accessories?.map((x) => standardAccessories[x])
    const filter = color ? COLOR_TO_FILTER_MAP[color] : null

    return (
        <div
            className="relative overflow-hidden select-none flex-none m-[-2px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: imgSize,
                height: imgSize,
            }}
        >
            <div
                className="object-cover absolute inset-0 rendering-pixelated bg-cover"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    filter: filter as any,
                    backgroundImage: `url(${spriteUrl(skin, 'wave')})`,
                    width: skin === 'robohog' ? '300%' : '400%', // RoboHog sprite is 3 tiles tall, while others are 4
                    height: skin === 'robohog' ? '300%' : '400%',
                }}
            />

            {accessoryInfos?.map((accessory, index) => (
                <img
                    key={index}
                    src={`${spriteAccessoryUrl(accessory.img)}`}
                    className="object-cover absolute inset-0 rendering-pixelated pointer-events-none"
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
            className="relative rounded-full overflow-hidden"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: size,
                height: size,
            }}
        >
            <div className="absolute top-0 left-0 w-full h-full transform translate-x-[-3%] translate-y-[10%] scale-[1.8]">
                <HedgehogBuddyStatic {...props} size={size} />
            </div>
        </div>
    )
}
