import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const KEYBOARD_GARDEN = {
    light: {
        baseColor: '#eeefe9',
        texture: 'https://res.cloudinary.com/dmukukwp6/image/upload/keyboard_garden_bg_light_03a349af5c.png',
        textureSize: '100px 100px',
        illustration:
            'https://res.cloudinary.com/dmukukwp6/image/upload/keyboard_garden_light_opt_compressed_5094746caf.png',
    },
    dark: {
        baseColor: '#1d1f27',
        texture: 'https://res.cloudinary.com/dmukukwp6/image/upload/keyboard_garden_bg_dark_9ab088797a.png',
        textureSize: '200px 200px',
        illustration: 'https://res.cloudinary.com/dmukukwp6/image/upload/keyboard_garden_dark_opt_15e213413c.png',
    },
}

// posthog.com "keyboard garden" wallpaper: base color, tiled texture, and a bottom-right illustration
// behind the content. themeLogic forces light mode on unauthenticated scenes, so the dark assets stay
// dormant on the auth pages for now.
export function KeyboardGardenBackground({ children }: { children?: ReactNode }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const assets = isDarkModeOn ? KEYBOARD_GARDEN.dark : KEYBOARD_GARDEN.light

    return (
        <div className="relative min-h-screen w-full overflow-hidden" style={{ backgroundColor: assets.baseColor }}>
            <div
                aria-hidden
                className="absolute inset-0 bg-repeat pointer-events-none"
                style={{ backgroundImage: `url(${assets.texture})`, backgroundSize: assets.textureSize }}
            />
            <img
                aria-hidden
                src={assets.illustration}
                alt=""
                draggable={false}
                className="absolute bottom-4 -right-4 max-w-none pointer-events-none select-none"
                style={{ width: 'clamp(14rem, 32vw, 32rem)', height: 'clamp(14rem, 32vw, 32rem)' }}
            />
            <div className="relative z-10 flex min-h-screen flex-col items-center justify-center">{children}</div>
        </div>
    )
}
