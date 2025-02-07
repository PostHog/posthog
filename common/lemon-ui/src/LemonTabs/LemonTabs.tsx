import './LemonTabs.scss'

import { IconInfo } from '@posthog/icons'
import clsx from 'clsx'

import { useSliderPositioning } from '../hooks'
import { Link } from '../Link'
import { Tooltip } from '../Tooltip'

/** A tab that represents one of the options, but doesn't have any content. Render tab-dependent UI yourself. */
export interface AbstractLemonTab<T extends string | number> {
    key: T
    label: string | JSX.Element
    tooltip?: string | JSX.Element
    /** URL of the tab if it can be linked to (which is usually a good practice). */
    link?: string
}

/** A tab with content. In this case the LemonTabs component automatically renders content of the active tab. */
export interface ConcreteLemonTab<T extends string | number> extends AbstractLemonTab<T> {
    content: JSX.Element
}

export type LemonTab<T extends string | number> = AbstractLemonTab<T> | ConcreteLemonTab<T>

export interface LemonTabsProps<T extends string | number> {
    activeKey: T
    onChange?: (key: T) => void
    /** List of tabs. Falsy entries are ignored - they're there to make conditional tabs convenient. */
    tabs: (LemonTab<T> | null | false)[]
    size?: 'small' | 'medium'
    'data-attr'?: string
    barClassName?: string
}

interface LemonTabsCSSProperties extends React.CSSProperties {
    '--lemon-tabs-slider-width': `${number}px`
    '--lemon-tabs-slider-offset': `${number}px`
}

export function LemonTabs<T extends string | number>({
    activeKey,
    onChange,
    tabs,
    barClassName,
    size = 'medium',
    'data-attr': dataAttr,
}: LemonTabsProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset, transitioning } = useSliderPositioning<
        HTMLUListElement,
        HTMLLIElement
    >(activeKey, 200)

    /** Tabs with falsy entries filtered out. */
    const realTabs = tabs.filter(Boolean) as LemonTab<T>[]
    const activeTab = realTabs.find((tab) => tab.key === activeKey)

    return (
        <div
            className={clsx('LemonTabs', transitioning && 'LemonTabs--transitioning', `LemonTabs--${size}`)}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-tabs-slider-width': `${sliderWidth}px`,
                    '--lemon-tabs-slider-offset': `${sliderOffset}px`,
                } as LemonTabsCSSProperties
            }
            data-attr={dataAttr}
        >
            <ul className={clsx('LemonTabs__bar', barClassName)} role="tablist" ref={containerRef}>
                {realTabs.map((tab) => {
                    const content = (
                        <>
                            {tab.label}
                            {tab.tooltip && <IconInfo className="ml-1 text-base shrink-0" />}
                        </>
                    )
                    return (
                        <Tooltip key={tab.key} title={tab.tooltip} placement="top" offset={0}>
                            <li
                                className={clsx('LemonTabs__tab', tab.key === activeKey && 'LemonTabs__tab--active')}
                                onClick={onChange ? () => onChange(tab.key) : undefined}
                                role="tab"
                                aria-selected={tab.key === activeKey}
                                tabIndex={0}
                                onKeyDown={
                                    onChange
                                        ? (e) => {
                                              if (e.key === 'Enter') {
                                                  onChange(tab.key)
                                              }
                                          }
                                        : undefined
                                }
                                ref={tab.key === activeKey ? selectionRef : undefined}
                            >
                                {tab.link ? (
                                    <Link className="LemonTabs__tab-content" to={tab.link}>
                                        {content}
                                    </Link>
                                ) : (
                                    <div className="LemonTabs__tab-content">{content}</div>
                                )}
                            </li>
                        </Tooltip>
                    )
                })}
            </ul>
            {activeTab && 'content' in activeTab && (
                <div className="LemonTabs__content" key={activeKey}>
                    {activeTab.content}
                </div>
            )}
        </div>
    )
}
