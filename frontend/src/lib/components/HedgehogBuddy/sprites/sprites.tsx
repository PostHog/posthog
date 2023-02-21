import hhFall from 'public/hedgehog/sprites/fall.png'
import hhJump from 'public/hedgehog/sprites/jump.png'
import hhSign from 'public/hedgehog/sprites/sign.png'
import hhSpin from 'public/hedgehog/sprites/spin.png'
import hhWalk from 'public/hedgehog/sprites/walk.png'
import hhWave from 'public/hedgehog/sprites/wave.png'
// import hhFallXmas from 'public/hedgehog/sprites/fall-xmas.png'
// import hhJumpXmas from 'public/hedgehog/sprites/jump-xmas.png'
// import hhSignXmas from 'public/hedgehog/sprites/sign-xmas.png'
// import hhSpinXmas from 'public/hedgehog/sprites/spin-xmas.png'
// import hhWalkXmas from 'public/hedgehog/sprites/walk-xmas.png'
// import hhWaveXmas from 'public/hedgehog/sprites/wave-xmas.png'

export const SPRITE_SIZE = 64
export const SPRITE_SHEET_WIDTH = 512

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
    },
    sign: {
        img: hhSign,
        frames: 33,
        maxIteration: 1,
        forceDirection: 'right',
        randomChance: 1,
    },
    spin: {
        img: hhSpin,
        frames: 9,
        maxIteration: 3,
        randomChance: 2,
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
}

// NOTE: Xmas animations are currently disabled, but leaving this here for next Xmas
// export const xmasAnimations: { [key: string]: SpriteInfo } = {
//     stop: {
//         img: hhWaveXmas,
//         frames: 1,
//         maxIteration: 50,
//         randomChance: 1,
//     },
//     fall: {
//         img: hhFallXmas,
//         frames: 9,
//         forceDirection: 'left',
//         randomChance: 0,
//     },
//     jump: {
//         img: hhJumpXmas,
//         frames: 10,
//         maxIteration: 10,
//         randomChance: 2,
//     },
//     sign: {
//         img: hhSignXmas,
//         frames: 33,
//         maxIteration: 1,
//         forceDirection: 'right',
//         randomChance: 1,
//     },
//     spin: {
//         img: hhSpinXmas,
//         frames: 9,
//         maxIteration: 3,
//         randomChance: 2,
//     },
//     walk: {
//         img: hhWalkXmas,
//         frames: 11,
//         maxIteration: 20,
//         randomChance: 10,
//     },
//     wave: {
//         img: hhWaveXmas,
//         frames: 27,
//         maxIteration: 1,
//         randomChance: 2,
//     },
// }
