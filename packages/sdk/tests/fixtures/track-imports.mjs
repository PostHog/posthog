import { appendFileSync } from 'node:fs'

let logPath

export function initialize(options) {
    logPath = options.logPath
}

export async function load(url, context, nextLoad) {
    const result = await nextLoad(url, context)
    appendFileSync(logPath, `${url}\n`)
    return result
}
