import laptophog from './laptophog.lottie'
import musichog from './musichog.lottie'
import sportshog from './sportshog.lottie'

/**
 * We're keeping lottiefiles in this folder.
 *
 * Even though these are `.json` files, we keep their filenames as `.lottie`. Doing otherwise makes prettier
 * explode their size. We're just `fetch`-ing these files, so let's treat them as binaries.
 *
 * See more: https://lottiefiles.com/
 */

export enum AnimationType {
    LaptopHog = 'laptophog',
    MusicHog = 'musichog',
    SportsHog = 'sportshog',
}

export const animations: Record<AnimationType, { url: string; width: number; height: number }> = {
    laptophog: { url: laptophog, width: 800, height: 800 },
    musichog: { url: musichog, width: 800, height: 800 },
    sportshog: { url: sportshog, width: 800, height: 800 },
}

const animationCache: Record<string, Record<string, any>> = {}
const fetchCache: Record<string, Promise<Record<string, any>>> = {}

async function fetchJson(url: string): Promise<Record<string, any>> {
    const response = await window.fetch(url)
    return await response.json()
}

export async function getAnimationSource(animation: AnimationType): Promise<Record<string, any>> {
    if (!animationCache[animation]) {
        if (!(animation in fetchCache)) {
            fetchCache[animation] = fetchJson(animations[animation].url)
        }
        animationCache[animation] = await fetchCache[animation]
    }
    return animationCache[animation]
}
