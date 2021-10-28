import { performance } from 'perf_hooks'

const roundToTwo = (n: number) => `${Math.round(n * 100) / 100}`

let _services: string
let _test: string
let _singular: string
let _plural: string
let _now: number

export function startLog(services: string, test: string, singular = 'req', plural = 'reqs'): void {
    _services = services
    _test = test
    _singular = singular
    _plural = plural
    _now = performance.now()
}

export function endLog(count: number): void {
    const timeMs = performance.now() - _now
    console.log(
        `[${_services}] ${_test}: ${count} ${count === 1 ? _singular : _plural}, ${roundToTwo(
            timeMs / 1000
        )} sec, ${roundToTwo(1000 / (timeMs / count))} ${_plural}/sec, ${roundToTwo(timeMs / count)}ms per ${_singular}`
    )
}
