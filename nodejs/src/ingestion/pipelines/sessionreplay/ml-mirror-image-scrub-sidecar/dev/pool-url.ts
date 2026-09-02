/** Starting a pool needs the worker's URL, which only an entry point can resolve: import.meta works
 *  under tsx but not under jest's CJS transform, which is why startPool takes it as a parameter
 *  rather than resolving it itself (see the note in src/pool.ts). Dev scripts share it here. */
import { type ScrubPool, startPool as start } from '../src/pool.ts'

export function startPool(size: number): Promise<ScrubPool> {
    return start(size, new URL('../src/scrub-worker.ts', import.meta.url))
}
