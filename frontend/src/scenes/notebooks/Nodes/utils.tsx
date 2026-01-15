import { ExtendedRegExpMatchArray, InputRule, NodeViewProps, PasteRule } from '@tiptap/core'
import { NodeType } from '@tiptap/pm/model'
import clsx from 'clsx'
import posthog from 'posthog-js'
import { type ReactNode, useCallback, useMemo, useRef } from 'react'

import { TTEditor } from 'lib/components/RichContentEditor/types'
import { percentage, tryJsonParse, uuid } from 'lib/utils'
import { formatCurrency } from 'lib/utils/geography/currency'

import { CurrencyCode } from '~/queries/schema/schema-general'
import { Group } from '~/types'

import { CustomNotebookNodeAttributes, NotebookNodeAttributes } from '../types'

export const INTEGER_REGEX_MATCH_GROUPS = '([0-9]*)(.*)'
export const SHORT_CODE_REGEX_MATCH_GROUPS = '([0-9a-zA-Z]*)(.*)'
export const UUID_REGEX_MATCH_GROUPS = '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(.*)'
export const OPTIONAL_PROJECT_NON_CAPTURE_GROUP = '(?:/project/[0-9]*)?'

type AnsiState = {
    fgClassName?: string
    isBold?: boolean
}

const ANSI_FG_CLASSNAMES: Record<number, string> = {
    30: 'text-muted',
    31: 'text-red',
    32: 'text-green',
    33: 'text-yellow',
    34: 'text-blue',
    35: 'text-purple',
    36: 'text-blue',
    37: 'text-default',
    90: 'text-muted',
    91: 'text-red',
    92: 'text-green',
    93: 'text-yellow',
    94: 'text-blue',
    95: 'text-purple',
    96: 'text-blue',
    97: 'text-default',
}

const applyAnsiCodes = (codes: number[], state: AnsiState): AnsiState => {
    let nextState: AnsiState = { ...state }

    for (const code of codes) {
        if (code === 0) {
            nextState = {}
            continue
        }

        if (code === 1) {
            nextState.isBold = true
            continue
        }

        if (code === 22) {
            nextState.isBold = false
            continue
        }

        if (code === 39) {
            delete nextState.fgClassName
            continue
        }

        const fgClassName = ANSI_FG_CLASSNAMES[code]
        if (fgClassName) {
            nextState.fgClassName = fgClassName
        }
    }

    return nextState
}

export const renderAnsiText = (value: string): ReactNode => {
    if (!value.includes('\u001b[')) {
        return value
    }

    const segments: ReactNode[] = []
    const ansiRegex = /\u001b\[([0-9;]*)m/g
    let lastIndex = 0
    let match = ansiRegex.exec(value)
    let state: AnsiState = {}

    const pushSegment = (text: string): void => {
        if (!text) {
            return
        }

        const className = clsx(state.fgClassName, state.isBold && 'font-semibold')
        if (className) {
            segments.push(
                <span key={`${segments.length}-${lastIndex}`} className={className}>
                    {text}
                </span>
            )
        } else {
            segments.push(text)
        }
    }

    while (match) {
        pushSegment(value.slice(lastIndex, match.index))
        const codes = match[1]
            ? match[1]
                  .split(';')
                  .map((code) => Number.parseInt(code, 10))
                  .filter((code) => Number.isFinite(code))
            : [0]
        state = applyAnsiCodes(codes, state)
        lastIndex = match.index + match[0].length
        match = ansiRegex.exec(value)
    }

    pushSegment(value.slice(lastIndex))

    return segments
}

export function createUrlRegex(path: string | RegExp, origin?: string): RegExp {
    origin = (origin || window.location.origin).replace('.', '\\.')
    return new RegExp(origin + path, 'ig')
}

export function reportNotebookNodeCreation(nodeType: string): void {
    posthog.capture('notebook node created', { type: nodeType })
}

export function posthogNodePasteRule(options: {
    find: string | RegExp
    type: NodeType
    editor: TTEditor
    getAttributes: (
        match: ExtendedRegExpMatchArray
    ) => Promise<Record<string, any> | null | undefined> | Record<string, any> | null | undefined
}): PasteRule {
    return new PasteRule({
        find: typeof options.find === 'string' ? createUrlRegex(options.find) : options.find,
        handler: ({ match, chain, range }) => {
            if (match.input) {
                chain().deleteRange(range).run()

                void Promise.resolve(options.getAttributes(match)).then((attributes) => {
                    if (attributes) {
                        options.editor.commands.insertContent({
                            type: options.type.name,
                            attrs: attributes,
                        })
                    }
                })
            }
        },
    })
}

export function posthogNodeInputRule(options: {
    find: string | RegExp
    type: NodeType
    editor: TTEditor
    getAttributes: (
        match: ExtendedRegExpMatchArray
    ) => Promise<Record<string, any> | null | undefined> | Record<string, any> | null | undefined
}): InputRule {
    return new InputRule({
        find: typeof options.find === 'string' ? createUrlRegex(options.find) : options.find,
        handler: ({ match, chain, range }) => {
            if (match.input) {
                chain().deleteRange(range).run()

                void Promise.resolve(options.getAttributes(match)).then((attributes) => {
                    if (attributes) {
                        options.editor.commands.insertContent({
                            type: options.type.name,
                            attrs: attributes,
                        })
                    }
                })
            }
        },
    })
}

export function linkPasteRule(): PasteRule {
    return new PasteRule({
        find: createUrlRegex(
            `(?!${window.location.host})([a-zA-Z0-9-._~:/?#\\[\\]!@$&'()*,;=]*)`,
            '^(https?|mailto)://'
        ),
        handler: ({ match, chain, range }) => {
            if (match.input) {
                const url = new URL(match[0])
                const href = url.origin === window.location.origin ? url.pathname : url.toString()
                chain()
                    .deleteRange(range)
                    .insertContent([
                        {
                            type: 'text',
                            marks: [{ type: 'link', attrs: { href } }],
                            text: href,
                        },
                        { type: 'text', text: ' ' },
                    ])
                    .run()
            }
        },
    })
}

export function useSyncedAttributes<T extends CustomNotebookNodeAttributes>(
    props: NodeViewProps
): [NotebookNodeAttributes<T>, (attrs: Partial<NotebookNodeAttributes<T>>) => void] {
    const nodeId = useMemo(() => props.node.attrs.nodeId ?? uuid(), [props.node.attrs.nodeId])
    const previousNodeAttrs = useRef<NodeViewProps['node']['attrs']>()
    const parsedAttrs = useRef<NotebookNodeAttributes<T>>({} as NotebookNodeAttributes<T>)

    if (previousNodeAttrs.current !== props.node.attrs) {
        const newParsedAttrs = {}

        Object.keys(props.node.attrs).forEach((key) => {
            if (previousNodeAttrs.current?.[key] !== props.node.attrs[key]) {
                // If changed, set it whilst trying to parse
                newParsedAttrs[key] = tryJsonParse(props.node.attrs[key], props.node.attrs[key])
            } else if (parsedAttrs.current) {
                // Otherwise use the old value to preserve object equality
                newParsedAttrs[key] = parsedAttrs.current[key]
            }
        })

        parsedAttrs.current = newParsedAttrs as NotebookNodeAttributes<T>
        parsedAttrs.current.nodeId = nodeId
    }

    previousNodeAttrs.current = props.node.attrs

    const updateAttributes = useCallback(
        (attrs: Partial<NotebookNodeAttributes<T>>): void => {
            // We call the update whilst json stringifying
            const stringifiedAttrs = Object.keys(attrs).reduce(
                (acc, x) => {
                    acc[x] = attrs[x] && typeof attrs[x] === 'object' ? JSON.stringify(attrs[x]) : attrs[x]
                    return acc
                },
                {} as Record<string, any>
            )

            const hasChanges = Object.keys(stringifiedAttrs).some(
                (key) => previousNodeAttrs.current?.[key] !== stringifiedAttrs[key]
            )

            if (!hasChanges) {
                return
            }

            // NOTE: queueMicrotask protects us from TipTap's flushSync calls, ensuring we never modify the state whilst the flush is happening
            queueMicrotask(() => props.updateAttributes(stringifiedAttrs))
        },
        // oxlint-disable-next-line exhaustive-deps
        [props.updateAttributes]
    )

    return [parsedAttrs.current, updateAttributes]
}

export const getLogicKey = ({
    tabId,
    personId,
    groupKey,
}: {
    tabId: string
    personId?: string
    groupKey?: string
}): string => {
    const entityKey = personId || groupKey
    return `${tabId}-${entityKey}`
}

export function sortProperties(entries: [string, any][], pinnedProperties: string[]): [string, any][] {
    const pinnedSet = new Set(pinnedProperties)
    const pinnedIndexMap = new Map(pinnedProperties.map((key, index) => [key, index]))

    return entries.sort(([aKey], [bKey]) => {
        const aIsPinned = pinnedSet.has(aKey)
        const bIsPinned = pinnedSet.has(bKey)

        if (aIsPinned && !bIsPinned) {
            return -1
        }
        if (!aIsPinned && bIsPinned) {
            return 1
        }

        // If both are pinned or both aren't, maintain their relative order
        // based on the pinnedProperties array order for pinned items
        if (aIsPinned && bIsPinned) {
            return pinnedIndexMap.get(aKey)! - pinnedIndexMap.get(bKey)!
        }

        return aKey.localeCompare(bKey)
    })
}

// Group revenue-related utilities

/**
 * Represents MRR data with forecasted trend
 */
export interface MRRData {
    mrr: number
    forecastedMrr: number | null
    percentageDiff: number | null
    tooltipText: string | null
    trendDirection: 'up' | 'down' | 'flat' | null
}

/**
 * Calculates MRR data with trend analysis and tooltip text
 * @param group Group data containing MRR information
 * @param baseCurrency Currency code for formatting
 * @returns MRRData object or null if no valid MRR
 */
export function calculateMRRData(group: Group, baseCurrency: CurrencyCode): MRRData | null {
    const mrrValue = group.group_properties.mrr
    const mrr: number | null = typeof mrrValue === 'number' && !isNaN(mrrValue) ? mrrValue : null
    const forecastedMrrValue = group.group_properties.forecasted_mrr
    const forecastedMrr: number | null =
        typeof forecastedMrrValue === 'number' && !isNaN(forecastedMrrValue) ? forecastedMrrValue : null

    if (mrr === null) {
        return null
    }

    const percentageDiff = forecastedMrr === null || mrr === 0 ? null : (forecastedMrr - mrr) / mrr

    let tooltipText: string | null = null
    let trendDirection: 'up' | 'down' | 'flat' | null = null

    if (percentageDiff !== null && forecastedMrr !== null) {
        if (percentageDiff > 0) {
            tooltipText = `${percentage(percentageDiff)} MRR growth forecasted to ${formatCurrency(forecastedMrr, baseCurrency)}`
            trendDirection = 'up'
        } else if (percentageDiff < 0) {
            tooltipText = `${percentage(-percentageDiff)} MRR decrease forecasted to ${formatCurrency(forecastedMrr, baseCurrency)}`
            trendDirection = 'down'
        } else {
            tooltipText = `No MRR change forecasted, flat at ${formatCurrency(mrr, baseCurrency)}`
            trendDirection = 'flat'
        }
    }

    return {
        mrr,
        forecastedMrr,
        percentageDiff,
        tooltipText,
        trendDirection,
    }
}

/**
 * Gets paid products with formatted names from group MRR data
 * @param group Group data containing MRR per product
 * @returns Array of formatted product names with positive MRR
 */
export function getPaidProducts(group: Group): string[] {
    const mrrPerProduct: Record<string, number> = group.group_properties.mrr_per_product || {}

    return Object.entries(mrrPerProduct)
        .filter(([, mrr]) => typeof mrr === 'number' && mrr > 0)
        .map(([product]) =>
            product
                .replaceAll('_', ' ')
                .split(' ')
                .map((word, index) => (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
                .join(' ')
        )
}

/**
 * Extracts customer lifetime value from group properties
 * @param group Group data containing customer lifetime value
 * @returns Lifetime value as number or null if invalid/missing
 */
export function getLifetimeValue(group: Group): number | null {
    const value = group.group_properties.customer_lifetime_value
    return typeof value === 'number' && !isNaN(value) ? value : null
}
