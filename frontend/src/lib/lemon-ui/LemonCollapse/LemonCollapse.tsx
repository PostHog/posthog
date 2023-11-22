import './LemonCollapse.scss'

import clsx from 'clsx'
import React, { ReactNode, useState } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING } from 'react-transition-group/Transition'
import useResizeObserver from 'use-resize-observer'

import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'

export interface LemonCollapsePanel<K extends React.Key> {
    key: K
    header: ReactNode
    content: ReactNode
}

interface LemonCollapsePropsBase<K extends React.Key> {
    /** Panels in order of display. Falsy values mean that the panel isn't rendered. */
    panels: (LemonCollapsePanel<K> | null | false)[]
    className?: string
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

type LemonCollapseProps<K extends React.Key> = LemonCollapsePropsSingle<K> | LemonCollapsePropsMultiple<K>

export function LemonCollapse<K extends React.Key>({
    panels,
    className,
    ...props
}: LemonCollapseProps<K>): JSX.Element {
    let isPanelExpanded: (key: K) => boolean
    let onPanelChange: (key: K, isExpanded: boolean) => void
    if (props.multiple) {
        const [localActiveKeys, setLocalActiveKeys] = useState<Set<K>>(new Set(props.defaultActiveKeys ?? []))
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
        const [localActiveKey, setLocalActiveKey] = useState<K | null>(props.defaultActiveKey ?? null)
        const effectiveActiveKey = props.activeKey ?? localActiveKey
        isPanelExpanded = (key: K) => key === effectiveActiveKey
        onPanelChange = (key: K, isExpanded: boolean): void => {
            props.onChange?.(isExpanded ? key : null)
            setLocalActiveKey(isExpanded ? key : null)
        }
    }

    return (
        <div className={clsx('LemonCollapse', className)}>
            {(panels.filter(Boolean) as LemonCollapsePanel<K>[]).map(({ key, ...panel }) => (
                <LemonCollapsePanel
                    key={key}
                    {...panel}
                    isExpanded={isPanelExpanded(key)}
                    onChange={(isExanded) => onPanelChange(key, isExanded)}
                />
            ))}
        </div>
    )
}

interface LemonCollapsePanelProps {
    header: ReactNode
    content: ReactNode
    isExpanded: boolean
    onChange: (isExpanded: boolean) => void
}

function LemonCollapsePanel({ header, content, isExpanded, onChange }: LemonCollapsePanelProps): JSX.Element {
    const { height: contentHeight, ref: contentRef } = useResizeObserver({ box: 'border-box' })

    return (
        <div className="LemonCollapsePanel" aria-expanded={isExpanded}>
            <LemonButton
                onClick={() => onChange(!isExpanded)}
                icon={isExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                status="stealth"
                className="LemonCollapsePanel__header"
            >
                {header}
            </LemonButton>
            <Transition in={isExpanded} timeout={200} mountOnEnter unmountOnExit>
                {(status) => (
                    <div
                        className="LemonCollapsePanel__body"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            status === ENTERING || status === ENTERED
                                ? {
                                      height: contentHeight,
                                  }
                                : undefined
                        }
                        aria-busy={status.endsWith('ing')}
                    >
                        <div className="LemonCollapsePanel__content" ref={contentRef}>
                            {content}
                        </div>
                    </div>
                )}
            </Transition>
        </div>
    )
}

LemonCollapse.Panel = LemonCollapsePanel
