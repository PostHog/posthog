import { type ELK } from 'elkjs'

let elkPromise: Promise<ELK> | null = null

export function getElk(): Promise<ELK> {
    if (!elkPromise) {
        elkPromise = import('elkjs/lib/elk.bundled.js').then(({ default: ELK }) => new ELK())
    }
    return elkPromise
}
