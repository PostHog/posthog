import * as crypto from 'crypto'
import { RE2JS } from 're2js'

import { ExecOptions, ExecResult, VMState, exec as hogExec, execAsync as hogExecAsync } from '@posthog/hogvm'

import { performQuery } from '~/queries/query'
import { HogQLASTQuery, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

const external = {
    crypto, // TODO: switch to webcrypto and polyfill on the node side
    regex: {
        match: (regex: string, value: string): boolean => {
            const { regex: newRegex, insensitive, multiline, dotall } = gatherRegExModifiers(regex, 's')
            const flags =
                (insensitive ? RE2JS.CASE_INSENSITIVE : 0) |
                (multiline ? RE2JS.MULTILINE : 0) |
                (dotall ? RE2JS.DOTALL : 0)
            return RE2JS.compile(newRegex, flags).matcher(value).find()
        },
    },
}

export function execHog(code: any[] | VMState, options?: ExecOptions): ExecResult {
    return hogExec(code, {
        external,
        ...options,
    })
}

export function execHogAsync(code: any[] | VMState, options?: ExecOptions): Promise<ExecResult> {
    return hogExecAsync(code, {
        external,
        ...options,
        asyncFunctions: {
            sleep: (seconds: number) => {
                return new Promise((resolve) => setTimeout(resolve, seconds * 1000))
            },
            run: async (queryInput: string | Record<string, any>) => {
                const queryNode: HogQLQuery | HogQLASTQuery =
                    typeof queryInput === 'object'
                        ? setLatestVersionsOnQuery(
                              {
                                  kind: NodeKind.HogQLASTQuery,
                                  query: queryInput,
                              },
                              { recursion: false }
                          )
                        : setLatestVersionsOnQuery(
                              { kind: NodeKind.HogQLQuery, query: queryInput },
                              { recursion: false }
                          )
                const response = await performQuery(queryNode)
                return { results: response.results, columns: response.columns }
            },
            fetch: () => {
                throw new Error('fetch is disabled in the browser')
            },
            posthogCapture: () => {
                throw new Error('posthogCapture is not yet supported here')
            },
            ...options?.asyncFunctions,
        },
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
