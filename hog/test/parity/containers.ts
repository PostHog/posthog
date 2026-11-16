import type { InputSpec } from './inputs'

export interface ContainerCase {
    type: 'proguard' | 'hermes' | 'dsym' | 'elf'
    input: InputSpec
}

const BLOCK = 128 * 1024
const WINDOW = 2 * 1024 * 1024

// Sizes around every boundary where libzstd's streaming output can differ from one-shot
// compression: the 128 KiB block (exact multiples get an extra empty last block in Rust), the 2 MiB
// window at level 3, and large inputs that use the circular input buffer.
const SIZES = [
    0,
    1,
    1000,
    BLOCK - 1,
    BLOCK,
    BLOCK + 1,
    2 * BLOCK,
    3 * BLOCK,
    WINDOW - 1,
    WINDOW,
    WINDOW + 1,
    WINDOW + BLOCK,
    3_000_000,
    4 * WINDOW,
    4 * WINDOW + 1,
]

export const CONTAINER_CASES: ContainerCase[] = [
    ...SIZES.map(
        (size, index): ContainerCase => ({ type: 'proguard', input: { generator: 'lines', seed: 1000 + index, size } })
    ),
    ...SIZES.map(
        (size, index): ContainerCase => ({ type: 'proguard', input: { generator: 'ascii', seed: 2000 + index, size } })
    ),
    ...SIZES.map(
        (size, index): ContainerCase => ({ type: 'elf', input: { generator: 'bytes', seed: 3000 + index, size } })
    ),
    { type: 'dsym', input: { generator: 'bytes', seed: 4000, size: 32 * 1024 * 1024 } },
    { type: 'hermes', input: { generator: 'ascii', seed: 5000, size: 5 * BLOCK } },
]
