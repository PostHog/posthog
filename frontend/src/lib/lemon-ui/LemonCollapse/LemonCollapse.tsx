import './LemonCollapse.scss'

import clsx from 'clsx'
import React, { ReactNode, useEffect, useMemo, useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { IconCollapse, IconExpand } from '@posthog/icons'

import { useAnimatedPresence } from 'lib/hooks/useAnimatedPresence'

import { LemonButton, LemonButtonProps } from '../LemonButton'

export interface LemonCollapsePanel<K extends React.Key> {
    key: K
    header: ReactNode | LemonButtonProps
    content: ReactNode
    dataAttr?: string
    className?: string
}

interface LemonCollapsePropsBase<K extends React.Key> {
    /** Panels in order of display. Falsy values mean that the panel isn't rendered. */
    panels: (LemonCollapsePanel<K> | null | false)[]
    className?: string
    size?: LemonButtonProps['size']
    embedded?: boolean
}

interface LemonCollapsePropsSingle<K extends React.Key> extends LemonCollapsePropsBase<K> {
    activeKey?: K
    defaultActiveKey?: K
    onChange?: (activeKey: K | null) => void
    multiple?: false
}

interface LemonCollapsePropsMultiple<K extends React.Key> extends LemonCollapsePropsBase<K> {
    activeKeys?: K[]
    defaultActiveKeys?: K[]
    onChange?: (activeKeys: K[]) => void
    multiple: true
}

export type LemonCollapseProps<K extends React.Key> = LemonCollapsePropsSingle<K> | LemonCollapsePropsMultiple<K>

export function LemonCollapse<K extends React.Key>({
    panels,
    className,
    size,
    embedded,
    ...props
}: LemonCollapseProps<K>): JSX.Element {
    let isPanelExpanded: (key: K) => boolean
    let onPanelChange: (key: K, isExpanded: boolean) => void
    if (props.multiple) {
        const defaultActiveKeys = props.defaultActiveKeys ?? []
        const defaultActiveKeysString = defaultActiveKeys.join(',')
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [localActiveKeys, setLocalActiveKeys] = useState<Set<K>>(new Set(defaultActiveKeys))
        // eslint-disable-next-line react-hooks/rules-of-hooks
        useEffect(() => {
            setLocalActiveKeys(new Set(defaultActiveKeys))
        }, [defaultActiveKeysString])
        const effectiveActiveKeys = props.activeKeys ? new Set(props.activeKeys) : localActiveKeys
        isPanelExpanded = (key: K) => effectiveActiveKeys.has(key)
        onPanelChange = (key: K, isExpanded: boolean): void => {
            const newActiveKeys = new Set(effectiveActiveKeys)
            if (isExpanded) {
                newActiveKeys.add(key)
            } else {
                newActiveKeys.delete(key)
            }
            props.onChange?.(Array.from(newActiveKeys))
            setLocalActiveKeys(newActiveKeys)
        }
    } else {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [localActiveKey, setLocalActiveKey] = useState<K | null>(props.defaultActiveKey ?? null)
        const effectiveActiveKey = props.activeKey ?? localActiveKey
        isPanelExpanded = (key: K) => key === effectiveActiveKey
        onPanelChange = (key: K, isExpanded: boolean): void => {
            props.onChange?.(isExpanded ? key : null)
            setLocalActiveKey(isExpanded ? key : null)
        }
    }

    const displayPanels = panels.filter(Boolean) as LemonCollapsePanel<K>[]
    const hasExpandablePanels = displayPanels.some((p) => !!p.content)

    return (
        <div className={clsx('LemonCollapse', embedded && 'LemonCollapse--embedded', className)}>
            {displayPanels.map(({ key, ...panel }) => (
                <LemonCollapsePanel
                    key={key}
                    {...panel}
                    size={size}
                    isExpanded={isPanelExpanded(key)}
                    indexUnexpanableHeader={hasExpandablePanels}
                    onChange={(isExanded) => onPanelChange(key, isExanded)}
                />
            ))}
        </div>
    )
}

interface LemonCollapsePanelProps {
    header: ReactNode | LemonButtonProps
    content: ReactNode
    isExpanded: boolean
    indexUnexpanableHeader: boolean
    size: LemonButtonProps['size']
    onChange: (isExpanded: boolean) => void
    className?: string
    dataAttr?: string
    onHeaderClick?: () => void
}

interface HeaderDefinition {
    headerChildren: ReactNode
    headerProps: LemonButtonProps
}

/** Must match the `transition: height` duration in LemonCollapse.scss. */
const COLLAPSE_TRANSITION_MS = 200

function LemonCollapsePanel({
    header,
    content,
    isExpanded,
    size,
    className,
    dataAttr,
    indexUnexpanableHeader,
    onChange,
    onHeaderClick,
}: LemonCollapsePanelProps): JSX.Element {
    const { height: contentHeight, ref: contentRef } = useResizeObserver({ box: 'border-box' })
    // The measured height is only trustworthy as a transition endpoint: ResizeObserver
    // notifications can be dropped (e.g. layout feedback loops in narrow panes), and pinning an
    // open panel to a stale measurement clips its content with no way to recover. So the panel
    // "settles" to height auto once the expand transition finishes, and only returns to numeric
    // heights for the animation frames themselves.
    const [settled, setSettled] = useState(isExpanded)
    const [presenceIn, setPresenceIn] = useState(isExpanded)

    useEffect(() => {
        if (isExpanded) {
            setPresenceIn(true)
            const timer = window.setTimeout(() => setSettled(true), COLLAPSE_TRANSITION_MS + 50)
            return () => window.clearTimeout(timer)
        }
        // Collapse in two steps: first repaint at a numeric height (CSS can't transition from
        // `auto`), then flip the presence input so the height → 0 transition actually runs
        setSettled(false)
        const raf = window.requestAnimationFrame(() => setPresenceIn(false))
        return () => window.cancelAnimationFrame(raf)
    }, [isExpanded])

    const { rendered, shown } = useAnimatedPresence(presenceIn, COLLAPSE_TRANSITION_MS)

    const { headerChildren, headerProps } = useMemo((): HeaderDefinition => {
        if (header && typeof header === 'object' && 'children' in header) {
            const { children, ...rest } = header as LemonButtonProps
            return { headerChildren: children, headerProps: rest }
        }

        return { headerChildren: header as ReactNode, headerProps: {} }
    }, [header])

    return (
        <div className="LemonCollapsePanel" aria-expanded={isExpanded}>
            {content ? (
                <LemonButton
                    {...headerProps}
                    fullWidth
                    className={clsx('LemonCollapsePanel__header', headerProps?.className)}
                    onClick={(e) => {
                        onHeaderClick && onHeaderClick()
                        onChange(!isExpanded)
                        headerProps.onClick?.(e)
                        e.stopPropagation()
                    }}
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    {...(dataAttr ? { 'data-attr': dataAttr } : {})}
                    size={size}
                >
                    {headerChildren}
                </LemonButton>
            ) : (
                <LemonButton
                    className="LemonCollapsePanel__header LemonCollapsePanel__header--disabled"
                    {...(dataAttr ? { 'data-attr': dataAttr } : {})}
                    size={size}
                    icon={indexUnexpanableHeader ? <div className="w-[1em] h-[1em]" /> : null}
                >
                    {headerChildren}
                </LemonButton>
            )}

            {rendered && (
                <div
                    className="LemonCollapsePanel__body"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: shown ? (settled ? 'auto' : contentHeight) : 0 }}
                    aria-busy={rendered !== shown}
                >
                    <div className={clsx('LemonCollapsePanel__content', className)} ref={contentRef}>
                        {content}
                    </div>
                </div>
            )}
        </div>
    )
}

LemonCollapse.Panel = LemonCollapsePanel
