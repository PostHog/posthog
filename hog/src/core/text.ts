export function kebabCase(name: string): string {
    return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
}

export function joinList(items: readonly string[], conjunction: string): string {
    return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} ${conjunction} ${items.at(-1)}`
}

export function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
    return `${count} ${count === 1 ? noun : pluralNoun}`
}

const SHELL_SAFE_ARG = /^[\w@%+=:,./-]+$/

export function shellQuote(arg: string, safe: RegExp = SHELL_SAFE_ARG): string {
    return safe.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}
