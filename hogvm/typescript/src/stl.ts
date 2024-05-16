function toConcatArg(arg: any): string {
    if (arg === null) {
        return ''
    }
    return String(arg)
}

async function httpGet(url: string, timeout: number = 5): Promise<string | null> {
    const timeoutPromise = new Promise<null>((_, reject) => {
        setTimeout(() => {
            reject(new Error(`Request timed out after ${timeout} seconds`))
        }, timeout * 1000)
    })

    try {
        const response = await Promise.race([fetch(url), timeoutPromise])
        if (!response || !response.ok) {
            throw new Error('Network response was not ok.')
        }
        return await response.text()
    } catch (error) {
        throw new Error(`Failed to fetch: ${error.message}`)
    }
}

export async function executeStlFunction(name: string, args: any[], timeout: number = 5): Promise<any> {
    switch (name) {
        case 'concat':
            return args.map((arg) => toConcatArg(arg)).join('')
        case 'match': {
            const regex = new RegExp(args[1])
            return regex.test(args[0])
        }
        case 'toString':
        case 'toUUID':
            return String(args[0])
        case 'toInt':
            return !isNaN(parseInt(args[0])) ? parseInt(args[0]) : null
        case 'toFloat':
            return !isNaN(parseFloat(args[0])) ? parseFloat(args[0]) : null
        case 'ifNull':
            return args[0] !== null ? args[0] : args[1]
        case 'length':
            return args[0].length
        case 'empty':
            return !args[0]
        case 'notEmpty':
            return !!args[0]
        case 'lower':
            return args[0].toLowerCase()
        case 'upper':
            return args[0].toUpperCase()
        case 'reverse':
            return args[0].split('').reverse().join('')
        case 'httpGet':
            return httpGet(args[0], timeout)
        case 'print':
            // eslint-disable-next-line no-console
            console.log(...args)
            return
        case 'sleep':
            await new Promise((resolve) => setTimeout(resolve, args[0] * 1000))
            return
        default:
            throw new Error(`Unsupported function call: ${name}`)
    }
}
