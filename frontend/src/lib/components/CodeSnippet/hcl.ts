import type { HLJSApi, Language } from 'highlight.js'

/**
 * HCL (HashiCorp Configuration Language) grammar for highlight.js.
 * Vendored from https://github.com/highlightjs/highlightjs-terraform
 * (no npm package available).
 */
export default function hcl(hljs: HLJSApi): Language {
    const NUMBERS = {
        className: 'number',
        begin: '\\b\\d+(\\.\\d+)?',
        relevance: 0,
    }
    const STRINGS: Language = {
        className: 'string',
        begin: '"',
        end: '"',
        contains: [
            {
                className: 'variable',
                begin: '\\${',
                end: '\\}',
                relevance: 9,
                contains: [
                    {
                        className: 'string',
                        begin: '"',
                        end: '"',
                    },
                    {
                        className: 'meta',
                        begin: '[A-Za-z_0-9]*\\(',
                        end: '\\)',
                        contains: [
                            NUMBERS,
                            {
                                className: 'string',
                                begin: '"',
                                end: '"',
                                contains: [
                                    {
                                        className: 'variable',
                                        begin: '\\${',
                                        end: '\\}',
                                        contains: [
                                            {
                                                className: 'string',
                                                begin: '"',
                                                end: '"',
                                                contains: [
                                                    {
                                                        className: 'variable',
                                                        begin: '\\${',
                                                        end: '\\}',
                                                    },
                                                ],
                                            },
                                            {
                                                className: 'meta',
                                                begin: '[A-Za-z_0-9]*\\(',
                                                end: '\\)',
                                            },
                                        ],
                                    },
                                ],
                            },
                            'self',
                        ],
                    },
                ],
            },
        ],
    }

    return {
        name: 'HCL',
        aliases: ['tf', 'hcl', 'terraform'],
        keywords: 'resource variable provider output locals module data terraform',
        literal: 'false true null',
        contains: [hljs.COMMENT('#', '$'), NUMBERS, STRINGS],
    }
}
