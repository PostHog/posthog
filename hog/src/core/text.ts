export function kebabCase(name: string): string {
    return name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
}

export function plural(count: number, noun: string, pluralNoun = `${noun}s`): string {
    return `${count} ${count === 1 ? noun : pluralNoun}`
}

export function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}
