export function createSeededRandom(seed: number): () => number {
    // LCG constants from Numerical Recipes
    let m = 0x80000000 // 2^31
    let a = 1103515245
    let c = 12345

    let state = seed ? seed : Math.floor(Math.random() * (m - 1))

    return function () {
        state = (a * state + c) % m
        return state / m
    }
}

export const deterministicRandom = createSeededRandom(1234)
