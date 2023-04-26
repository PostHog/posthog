import hhFall from 'public/hedgehog/sprites/fall.png'
import hhJump from 'public/hedgehog/sprites/jump.png'
import hhSign from 'public/hedgehog/sprites/sign.png'
import hhWalk from 'public/hedgehog/sprites/walk.png'
import hhWave from 'public/hedgehog/sprites/wave.png'
import hhHeatmaps from 'public/hedgehog/sprites/heatmaps.png'
import hhFlag from 'public/hedgehog/sprites/flag.png'
import hhInspect from 'public/hedgehog/sprites/inspect.png'
import hhPhone from 'public/hedgehog/sprites/phone.png'
import hhAction from 'public/hedgehog/sprites/action.png'

import hhBeret from 'public/hedgehog/sprites/accessories/beret.png'
import hhCap from 'public/hedgehog/sprites/accessories/cap.png'
import hhChef from 'public/hedgehog/sprites/accessories/chefs-hat.png'
import hhCowboy from 'public/hedgehog/sprites/accessories/cowboy-hat.png'
import hhPatch from 'public/hedgehog/sprites/accessories/eyepatch.png'
import hhGlasses from 'public/hedgehog/sprites/accessories/glasses.png'
import hhGrad from 'public/hedgehog/sprites/accessories/graduation-hat.png'
import hhKid from 'public/hedgehog/sprites/accessories/kids-hat.png'
import hhParrot from 'public/hedgehog/sprites/accessories/parrot.png'
import hhParty from 'public/hedgehog/sprites/accessories/party-hat.png'
import hhPineapple from 'public/hedgehog/sprites/accessories/pineapple-hat.png'
import hhSunny from 'public/hedgehog/sprites/accessories/sunglasses.png'
import hhFancy from 'public/hedgehog/sprites/accessories/top-hat.png'

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
    group: typeof accessoryGroups[number]
    topOffset?: number
}

export const standardAnimations: { [key: string]: SpriteInfo } = {
    stop: {
        img: hhWave,
        frames: 1,
        maxIteration: 50,
        randomChance: 1,
    },
    fall: {
        img: hhFall,
        frames: 9,
        forceDirection: 'left',
        randomChance: 0,
    },
    jump: {
        img: hhJump,
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
        img: hhSign,
        frames: 33,
        maxIteration: 1,
        forceDirection: 'right',
        randomChance: 1,
    },
    walk: {
        img: hhWalk,
        frames: 11,
        maxIteration: 20,
        randomChance: 10,
    },
    wave: {
        img: hhWave,
        frames: 27,
        maxIteration: 1,
        randomChance: 2,
    },
    heatmaps: {
        img: hhHeatmaps,
        frames: 14,
        maxIteration: 1,
        randomChance: 0,
    },
    flag: {
        img: hhFlag,
        frames: 25,
        maxIteration: 1,
        randomChance: 1,
    },
    inspect: {
        img: hhInspect,
        frames: 36,
        maxIteration: 1,
        randomChance: 1,
    },
    phone: {
        img: hhPhone,
        frames: 28,
        maxIteration: 1,
        randomChance: 1,
    },
    action: {
        img: hhAction,
        frames: 8,
        maxIteration: 3,
        randomChance: 1,
    },
}

export const standardAccessories: { [key: string]: AccessoryInfo } = {
    beret: {
        img: hhBeret,
        group: 'headwear',
        topOffset: 10,
    },
    cap: {
        img: hhCap,
        group: 'headwear',
        topOffset: 10,
    },
    chef: {
        img: hhChef,
        group: 'headwear',
        topOffset: 10,
    },
    cowboy: {
        img: hhCowboy,
        group: 'headwear',
        topOffset: 10,
    },
    eyepatch: {
        img: hhPatch,
        group: 'eyewear',
        topOffset: 20,
    },
    nerdy: {
        img: hhGlasses,
        group: 'eyewear',
        topOffset: 20,
    },
    graduate: {
        img: hhGrad,
        group: 'headwear',
        topOffset: 10,
    },
    kiddo: {
        img: hhKid,
        group: 'headwear',
        topOffset: 10,
    },
    parrot: {
        img: hhParrot,
        group: 'other',
        topOffset: 20,
    },
    party: {
        img: hhParty,
        group: 'headwear',
        topOffset: 10,
    },
    pineapple: {
        img: hhPineapple,
        group: 'headwear',
        topOffset: 10,
    },
    sunshine: {
        img: hhSunny,
        group: 'eyewear',
        topOffset: 20,
    },
    fancy: {
        img: hhFancy,
        group: 'headwear',
        topOffset: 10,
    },
}
