import { ExecOptions } from '../types'

/** Extract (?-i) strings from regex */
function gatherModifiers(regex: string, initialModifiers: string): { regex: string; modifiers: string } {
    let insensitive = false
    let multiline = false
    let dotall = true // defaults to true on clickhouse

    function setModifier(modifier: string, negative: boolean): void {
        switch (modifier) {
            case 'i':
                insensitive = !negative
                break
            case 'm':
                multiline = !negative
                break
            case 's':
                dotall = !negative
                break
        }
    }
    // set defaults
    for (const modifier of initialModifiers.split('')) {
        setModifier(modifier, false)
    }
    regex = regex.replaceAll(/\(\?(-?)([ims]+)\)/g, (_, negative, modifiers) => {
        for (const modifier of modifiers.split('')) {
            setModifier(modifier, negative === '-')
        }
        return ''
    })
    return { regex, modifiers: `${insensitive ? 'i' : ''}${multiline ? 'm' : ''}${dotall ? 's' : ''}` }
}

export function match(regex: string, value: string, options?: ExecOptions): boolean {
    if (options?.external?.re2) {
        return new options.external.re2(regex, 's').test(value)
    }
    const { regex: newRegex, modifiers } = gatherModifiers(regex, 's')
    return new RegExp(newRegex, modifiers).test(value)
}

export function matchInsensitive(regex: string, value: string, options?: ExecOptions): boolean {
    if (options?.external?.re2) {
        return new options.external.re2(regex, 'is').test(value)
    }
    const { regex: newRegex, modifiers } = gatherModifiers(regex, 'is')
    return new RegExp(newRegex, modifiers).test(value)
}
