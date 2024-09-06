import { HedgehogConfig } from '~/types'

import { COLOR_TO_FILTER_MAP } from './hedgehogBuddyLogic'
import { spriteAccessoryUrl, spriteUrl, standardAccessories } from './sprites/sprites'

export type HedgehogBuddyStaticProps = Partial<HedgehogConfig> & { size?: number | string; waveOnAppearance?: boolean }

// Takes a range of options and renders a static hedgehog
export function HedgehogBuddyStatic({
    accessories,
    color,
    size,
    waveOnAppearance,
    skin = 'default',
}: HedgehogBuddyStaticProps): JSX.Element {
    const imgSize = size ?? 60

    const accessoryInfos = accessories?.map((x) => standardAccessories[x])
    const filter = color ? COLOR_TO_FILTER_MAP[color] : null

    // const [animationIteration, setAnimationIteration] = useState(waveOnAppearance ? 1 : 0)
    // const [_, setTimerLoop] = useState(0)
    // const animationFrameRef = useRef(0)

    // useEffect(() => {
    //     if (animationIteration) {
    //         setTimerLoop(0)
    //         let timer: any = null
    //         const loop = (): void => {
    //             if (animationFrameRef.current < standardAnimations.wave.frames) {
    //                 animationFrameRef.current++
    //                 timer = setTimeout(loop, 1000 / FPS)
    //             } else {
    //                 animationFrameRef.current = 0
    //             }
    //             setTimerLoop((x) => x + 1)
    //         }
    //         loop()
    //         return () => {
    //             clearTimeout(timer)
    //         }
    //     }
    // }, [animationIteration])

    return (
        <div
            className="relative overflow-hidden select-none flex-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: imgSize,
                height: imgSize,
                margin: -2,
            }}
            // onClick={waveOnAppearance ? () => setAnimationIteration((x) => x + 1) : undefined}
        >
            <div
                className="object-cover absolute inset-0 image-pixelated"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: '400%',
                    height: '400%',
                    filter: filter as any,
                    backgroundImage: `url(${spriteUrl(skin, 'wave')})`,
                    // backgroundPosition: `-${((animationFrameRef.current - 1) % X_FRAMES) * SPRITE_SIZE}px -${
                    //     Math.floor((animationFrameRef.current - 1) / X_FRAMES) * SPRITE_SIZE
                    // }px`,
                }}
            />

            {accessoryInfos?.map((accessory, index) => (
                <img
                    key={index}
                    src={`${spriteAccessoryUrl(accessory.img)}`}
                    className="object-cover absolute inset-0 image-pixelated pointer-events-none"
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
