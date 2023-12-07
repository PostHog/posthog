export const SPRITE_SIZE = 80
export const SHADOW_HEIGHT = SPRITE_SIZE / 8
export const SPRITE_SHEET_WIDTH = SPRITE_SIZE * 8

type SpriteInfo = {
    /** Number of frames in this sprite sheet */
    frames: number
    /** Path to the sprite sheet */
    img: string
    /** How many times to loop through the sprite sheet before stopping. If not set, will loop forever (so needs custom logic to decide when to end) */
    maxIteration?: number
    /** If set, will force the sprite to always face this direction */
    forceDirection?: 'left' | 'right'
    /** How likely this animation is to be chosen. Higher numbers are more likely. */
    randomChance?: number
    accessoryPositions?: [number, number][]
}

export const accessoryGroups = ['headwear', 'eyewear', 'other'] as const

export type AccessoryInfo = {
    /** Path to the img */
    img: string
    group: (typeof accessoryGroups)[number]
    topOffset?: number
}

// If loaded via the toolbar the root domain won't be app.posthog.com and so the assets won't load
// Simple workaround is we detect if the domain is localhost and if not we just use https://app.posthog.com
export const baseSpritePath = (): string => {
    let path = `/static/hedgehog/sprites`

    if (window.location.hostname !== 'localhost') {
        path = `https://app.posthog.com${path}`
    }

    return path
}
export const baseSpriteAccessoriesPath = (): string => `${baseSpritePath()}/accessories`

export const standardAnimations: { [key: string]: SpriteInfo } = {
    stop: {
        img: 'wave',
        frames: 1,
        maxIteration: 50,
        randomChance: 1,
    },
    fall: {
        img: 'fall',
        frames: 9,
        forceDirection: 'left',
        randomChance: 0,
    },
    jump: {
        img: 'jump',
        frames: 10,
        maxIteration: 10,
        randomChance: 2,
        accessoryPositions: [
            [0, 0],
            [0, 1],
            [0, 2],
            [0, 0],
            [0, -3],
            [0, -5],
            [0, -5],
            [0, -4],
            [0, -2],
            [0, -1],
        ],
    },
    sign: {
        img: 'sign',
        frames: 33,
        maxIteration: 1,
        forceDirection: 'right',
        randomChance: 1,
    },
    walk: {
        img: 'walk',
        frames: 11,
        maxIteration: 20,
        randomChance: 10,
    },
    wave: {
        img: 'wave',
        frames: 27,
        maxIteration: 1,
        randomChance: 2,
    },
    heatmaps: {
        img: 'heatmaps',
        frames: 14,
        maxIteration: 1,
        randomChance: 0,
    },
    flag: {
        img: 'flag',
        frames: 25,
        maxIteration: 1,
        randomChance: 1,
    },
    inspect: {
        img: 'inspect',
        frames: 36,
        maxIteration: 1,
        randomChance: 1,
    },
    phone: {
        img: 'phone',
        frames: 28,
        maxIteration: 1,
        randomChance: 1,
    },
    action: {
        img: 'action',
        frames: 8,
        maxIteration: 3,
        randomChance: 1,
    },
}

export const standardAccessories: { [key: string]: AccessoryInfo } = {
    xmas_hat: {
        img: 'xmas-hat',
        group: 'headwear',
        topOffset: 10,
    },
    xmas_antlers: {
        img: 'xmas-antlers',
        group: 'headwear',
        topOffset: 10,
    },
    xmas_scarf: {
        img: 'xmas-scarf',
        group: 'other',
        topOffset: 20,
    },
    beret: {
        img: 'beret',
        group: 'headwear',
        topOffset: 10,
    },
    cap: {
        img: 'cap',
        group: 'headwear',
        topOffset: 10,
    },
    chef: {
        img: 'chef',
        group: 'headwear',
        topOffset: 10,
    },
    cowboy: {
        img: 'cowboy',
        group: 'headwear',
        topOffset: 10,
    },
    eyepatch: {
        img: 'eyepatch',
        group: 'eyewear',
        topOffset: 20,
    },
    flag: {
        img: 'flag',
        group: 'headwear',
        topOffset: 10,
    },
    glasses: {
        img: 'glasses',
        group: 'eyewear',
        topOffset: 20,
    },
    graduation: {
        img: 'graduation',
        group: 'headwear',
        topOffset: 10,
    },

    parrot: {
        img: 'parrot',
        group: 'other',
        topOffset: 20,
    },
    party: {
        img: 'party',
        group: 'headwear',
        topOffset: 10,
    },
    pineapple: {
        img: 'pineapple',
        group: 'headwear',
        topOffset: 10,
    },
    sunglasses: {
        img: 'sunglasses',
        group: 'eyewear',
        topOffset: 20,
    },
    tophat: {
        img: 'tophat',
        group: 'headwear',
        topOffset: 10,
    },
}
