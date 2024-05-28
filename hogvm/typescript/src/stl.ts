export const STL: Record<string, (args: any[], name: string, timeout: number) => any> = {
    concat: (args) => {
        return args.map((arg: any) => (arg === null ? '' : String(arg))).join('')
    },
    match: (args) => {
        const regex = new RegExp(args[1])
        return regex.test(args[0])
    },
    toString: (args: any[]) => {
        return String(args[0])
    },
    toUUID: (args) => {
        return String(args[0])
    },
    toInt: (args) => {
        return !isNaN(parseInt(args[0])) ? parseInt(args[0]) : null
    },
    toFloat: (args) => {
        return !isNaN(parseFloat(args[0])) ? parseFloat(args[0]) : null
    },
    ifNull: (args) => {
        return args[0] !== null ? args[0] : args[1]
    },
    length: (args) => {
        return args[0].length
    },
    empty: (args) => {
        return !args[0]
    },
    notEmpty: (args) => {
        return !!args[0]
    },
    lower: (args) => {
        return args[0].toLowerCase()
    },
    upper: (args) => {
        return args[0].toUpperCase()
    },
    reverse: (args) => {
        return args[0].split('').reverse().join('')
    },
    print: (args) => {
        // eslint-disable-next-line no-console
        console.log(...args)
    },
    sleep: async (args) => {
        await new Promise((resolve) => setTimeout(resolve, args[0] * 1000))
    },
}
