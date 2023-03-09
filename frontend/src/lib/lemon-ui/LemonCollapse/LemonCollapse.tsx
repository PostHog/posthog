import React, { ReactNode, useState } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING } from 'react-transition-group/Transition'
import useResizeObserver from 'use-resize-observer'
import { IconUnfoldLess, IconUnfoldMore } from '../icons'
import { LemonButton } from '../LemonButton'
import './LemonCollapse.scss'

export interface LemonCollapsePanel<K extends React.Key> {
    key: K
    header: string
    content: ReactNode
}

export interface LemonCollapseProps<K extends React.Key> {
    panels: LemonCollapsePanel<K>[]
    activeKeys?: Set<K>
    onChange?: (activeKeys: Set<K>) => void
}

export function LemonCollapse<K extends React.Key>({
    panels,
    activeKeys,
    onChange,
}: LemonCollapseProps<K>): JSX.Element {
    const [localActiveKeys, setLocalActiveKeys] = useState<Set<K>>(activeKeys ?? new Set())

    function panelSpecificOnChange(key: K, isExpanded: boolean): void {
        const newActiveKeys = new Set(localActiveKeys)
        if (isExpanded) {
            newActiveKeys.add(key)
        } else {
            newActiveKeys.delete(key)
        }
        onChange?.(newActiveKeys)
        setLocalActiveKeys(newActiveKeys)
    }

    return (
        <div className="LemonCollapse">
            {panels.map(({ key, ...panel }) => (
                <LemonCollapsePanel
                    key={key}
                    {...panel}
                    isExpanded={localActiveKeys.has(key)}
                    onChange={(isExanded) => panelSpecificOnChange(key, isExanded)}
                />
            ))}
        </div>
    )
}

interface LemonCollapsePanelProps {
    header: string
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
