/**
 * highlight.js Terraform (HCL) language definition
 * Adapted from https://github.com/highlightjs/highlightjs-terraform
 */
import type { HLJSApi, Language, Mode } from 'highlight.js'

export default function terraform(hljs: HLJSApi): Language {
    const NUMBERS: Mode = {
        className: 'number',
        begin: '\\b\\d+(\\.\\d+)?',
        relevance: 0,
    }

    const STRINGS: Mode = {
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
        name: 'Terraform',
        aliases: ['tf', 'hcl'],
        keywords: {
            keyword: 'resource variable provider output locals module data terraform',
            literal: 'false true null',
        },
        contains: [hljs.COMMENT('\\#', '$'), NUMBERS, STRINGS],
    }
}
