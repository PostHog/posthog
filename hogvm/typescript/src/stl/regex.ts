import { RE2JS } from 're2js'

export function match(regex: string, value: string, flags: number = 0): boolean {
    // Unlike re2's default behavior, "." matches line breaks in ClickHouse by default
    flags = flags | RE2JS.DOTALL
    // extract all (?[ims]) and (?-[ims]) groups and apply them to the flags
    regex = regex.replaceAll(/\(\?(-?)([ims]+)\)/g, (flagGroup, negative, modifiers) => {
        for (const modifier of modifiers.split('')) {
            switch (modifier) {
                case 'i':
                    flags = negative ? flags & ~RE2JS.CASE_INSENSITIVE : flags | RE2JS.CASE_INSENSITIVE
                    break
                case 'm':
                    flags = negative ? flags & ~RE2JS.MULTILINE : flags | RE2JS.MULTILINE
                    break
                case 's':
                    flags = negative ? flags & ~RE2JS.DOTALL : flags | RE2JS.DOTALL
                    break
            }
        }
        return ''
    })
    return RE2JS.compile(regex, flags).matcher(value).find()
}

export function matchInsensitive(regex: string, value: string, flags: number = 0): boolean {
    return match(regex, value, RE2JS.CASE_INSENSITIVE | flags)
}
