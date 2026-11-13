export function kebabCase(name: string): string {
    return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
}

export function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
    return `${count} ${count === 1 ? noun : pluralNoun}`
}

const SHELL_SAFE_ARG = /^[\w@%+=:,./-]+$/

export function shellQuote(arg: string, safe: RegExp = SHELL_SAFE_ARG): string {
    return safe.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}
