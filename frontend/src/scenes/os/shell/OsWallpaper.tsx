import { cn } from 'lib/utils/css-classes'

import type { OsWallpaperKey } from './osWallpapers'
import bgDark from './wallpapers/bg-dark.webp'
import bgLight from './wallpapers/bg-light.webp'
import carpetDark from './wallpapers/carpet-dark.webp'
import carpetLight from './wallpapers/carpet-light.webp'
import hedgeDark from './wallpapers/hedge-dark.webp'
import hedgeLight from './wallpapers/hedge-light.webp'
import hogzilla from './wallpapers/hogzilla.webp'
import monopolyDark from './wallpapers/monopoly-dark.webp'
import monopolyLight from './wallpapers/monopoly-light.webp'
import office from './wallpapers/office.webp'

// Light and dark layers cross-fade when the theme changes.
const LIGHT_LAYER =
    'opacity-100 dark:opacity-0 transition-opacity duration-700 ease-in-out motion-reduce:transition-none'
const DARK_LAYER =
    'opacity-0 dark:opacity-100 transition-opacity duration-700 ease-in-out motion-reduce:transition-none'

function KeyboardGarden(): JSX.Element {
    return (
        <>
            <div className="absolute inset-0 bg-gradient-to-b from-[#FDEECD] to-[#FFFEF4]" />
            <div className={cn('absolute inset-0', LIGHT_LAYER)}>
                <img src={bgLight} alt="" className="size-full object-cover object-right-bottom" />
            </div>
            <div className={cn('absolute inset-0', DARK_LAYER)}>
                <img src={bgDark} alt="" className="size-full object-cover object-right-bottom" />
            </div>
            {/* The artwork is 777px wide at its native density, as on posthog.com. */}
            <div className="absolute bottom-0 right-0 grid">
                <img
                    src={hedgeLight}
                    alt=""
                    draggable={false}
                    className={cn('col-start-1 row-start-1 w-[777px] max-w-full', LIGHT_LAYER)}
                />
                <img
                    src={hedgeDark}
                    alt=""
                    draggable={false}
                    className={cn('col-start-1 row-start-1 w-[777px] max-w-full', DARK_LAYER)}
                />
            </div>
        </>
    )
}

function Hogzilla(): JSX.Element {
    return (
        <>
            <div
                className={cn('absolute inset-0 bg-[linear-gradient(268.63deg,#E3E1E4_0%,#FDFDFD_80%)]', LIGHT_LAYER)}
            />
            <div className={cn('absolute inset-0 bg-[linear-gradient(180deg,#141E40_0%,#46368B_100%)]', DARK_LAYER)} />
            <div className="absolute inset-0 flex items-end justify-end">
                <img src={hogzilla} alt="" draggable={false} className="w-full max-w-[1780px] h-auto" />
            </div>
        </>
    )
}

function StartupMonopoly(): JSX.Element {
    return (
        <>
            <div className="absolute inset-0 bg-[#E7E0DA] dark:bg-[#686E88] transition-colors duration-700 motion-reduce:transition-none" />
            {/* Half the source size, so the board stays sharp on high-density screens. */}
            <img
                src={monopolyLight}
                alt=""
                draggable={false}
                className={cn('absolute right-0 top-0 w-[1483.5px] max-w-full', LIGHT_LAYER)}
            />
            <img
                src={monopolyDark}
                alt=""
                draggable={false}
                className={cn('absolute right-0 top-0 w-[1483.5px] max-w-full', DARK_LAYER)}
            />
        </>
    )
}

function OfficeParty(): JSX.Element {
    return (
        <>
            <div
                className="absolute inset-0 bg-repeat bg-[length:200px_198px]"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundImage: `url(${carpetLight})` }}
            />
            <div
                className={cn('absolute inset-0 bg-repeat bg-[length:200px_198px]', DARK_LAYER)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundImage: `url(${carpetDark})` }}
            />
            <img src={office} alt="" draggable={false} className="absolute bottom-12 left-36 w-[498.5px]" />
        </>
    )
}

const SCENES: Record<OsWallpaperKey, () => JSX.Element> = {
    'keyboard-garden': KeyboardGarden,
    hogzilla: Hogzilla,
    'startup-monopoly': StartupMonopoly,
    'office-party': OfficeParty,
}

/** The desktop artwork. Only the chosen scene mounts, so the other scenes' images never download. */
export function OsWallpaper({ wallpaper }: { wallpaper: OsWallpaperKey }): JSX.Element {
    const Scene = SCENES[wallpaper]
    return (
        <div
            aria-hidden
            className="absolute inset-0 select-none overflow-hidden pointer-events-none"
            data-attr="os-wallpaper"
        >
            <Scene />
        </div>
    )
}
