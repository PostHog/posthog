import { exec as hogExec, ExecOptions, ExecResult, VMState } from '@posthog/hogvm'
import * as crypto from 'crypto'
import { RE2JS } from 're2js'

export function execHog(code: any[] | VMState, options?: ExecOptions): ExecResult {
    return hogExec(code, {
        external: {
            crypto, // TODO: switch to webcrypto and polyfill on the node side
            regex: {
                match: (regex: string, str: string): boolean => {
                    const { regex: newRegex, insensitive, multiline, dotall } = gatherRegExModifiers(regex, 's')
                    const flags =
                        (insensitive ? RE2JS.CASE_INSENSITIVE : 0) |
                        (multiline ? RE2JS.MULTILINE : 0) |
                        (dotall ? RE2JS.DOTALL : 0)
                    return RE2JS.compile(newRegex, flags).matcher(str).find()
                },
            },
        },
        ...(options ?? {}),
    })
}

function gatherRegExModifiers(
    regex: string,
    initialModifiers: string
): { regex: string; insensitive: boolean; multiline: boolean; dotall: boolean } {
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
    return { regex, insensitive, multiline, dotall }
}
