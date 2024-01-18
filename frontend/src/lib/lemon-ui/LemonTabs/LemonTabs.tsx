import './LemonTabs.scss'

import clsx from 'clsx'
import { AlignType } from 'rc-trigger/lib/interface'

import { useSliderPositioning } from '../hooks'
import { IconInfo } from '../icons'
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
    'data-attr'?: string
}

interface LemonTabsCSSProperties extends React.CSSProperties {
    '--lemon-tabs-slider-width': `${number}px`
    '--lemon-tabs-slider-offset': `${number}px`
}

/** Custom tooltip placement so that it's is closely aligned with the tabs, instead of being distanced. */
const TAB_TOOLTIP_PLACEMENTS: Record<string, AlignType> = {
    top: {
        points: ['bc', 'tc'], // Bottom-center of tooltip aligned to top-center of target
        offset: [0, 4], // This is the key change - positioning the tooltip lower to align arrow tip and top of tab
        overflow: {
            adjustX: 0,
            adjustY: 0,
        },
    },
}

export function LemonTabs<T extends string | number>({
    activeKey,
    onChange,
    tabs,
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
            className={clsx('LemonTabs', transitioning && 'LemonTabs--transitioning')}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-tabs-slider-width': `${sliderWidth}px`,
                    '--lemon-tabs-slider-offset': `${sliderOffset}px`,
                } as LemonTabsCSSProperties
            }
            data-attr={dataAttr}
        >
            <ul className="LemonTabs__bar" role="tablist" ref={containerRef}>
                {realTabs.map((tab) => {
                    const content = (
                        <>
                            {tab.label}
                            {tab.tooltip && <IconInfo className="ml-1 text-base shrink-0" />}
                        </>
                    )
                    return (
                        <Tooltip key={tab.key} title={tab.tooltip} builtinPlacements={TAB_TOOLTIP_PLACEMENTS}>
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
