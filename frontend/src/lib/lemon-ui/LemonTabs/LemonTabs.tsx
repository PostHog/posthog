import clsx from 'clsx'
import { AlignType } from 'rc-trigger/lib/interface'
import { useSliderPositioning } from '../hooks'
import { IconInfo } from '../icons'
import { Tooltip } from '../Tooltip'
import './LemonTabs.scss'

/** A tab that represents one of the options, but doesn't have any content. Render tab-dependent UI yourself. */
export interface AbstractLemonTab<T extends string> {
    key: T
    label: string | JSX.Element
    tooltip?: string | JSX.Element
}

/** A tab with content. In this case the LemonTabs component automatically renders content of the active tab. */
export interface ConcreteLemonTab<T extends string> extends AbstractLemonTab<T> {
    content: JSX.Element
}

export type LemonTab<T extends string> = AbstractLemonTab<T> | ConcreteLemonTab<T>

export interface LemonTabsProps<T extends string> {
    activeKey: T
    onChange: (key: T) => void
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

export function LemonTabs<T extends string>({
    activeKey,
    onChange,
    tabs,
    'data-attr': dataAttr,
}: LemonTabsProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset } = useSliderPositioning<
        HTMLDivElement,
        HTMLLIElement
    >(activeKey)

    /** Tabs with falsy entries filtered out. */
    const realTabs = tabs.filter(Boolean) as LemonTab<T>[]
    const activeTab = realTabs.find((tab) => tab.key === activeKey)

    if (!activeTab) {
        throw new Error(`No tab found with key ${activeKey}`)
    }

    return (
        <div
            className="LemonTabs"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--lemon-tabs-slider-width': `${sliderWidth}px`,
                    '--lemon-tabs-slider-offset': `${sliderOffset}px`,
                } as LemonTabsCSSProperties
            }
            data-attr={dataAttr}
        >
            <div className="LemonTabs__bar" role="tablist" ref={containerRef}>
                <ul>
                    {sliderWidth > 0 && <div className="LemonTabs__slider" />}
                    {realTabs.map((tab) => (
                        <Tooltip key={tab.key} title={tab.tooltip} builtinPlacements={TAB_TOOLTIP_PLACEMENTS}>
                            <li
                                className={clsx('LemonTabs__tab', tab.key === activeKey && 'LemonTabs__tab--active')}
                                onClick={() => onChange(tab.key)}
                                role="tab"
                                aria-selected={tab.key === activeKey}
                                tabIndex={0}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        onChange(tab.key)
                                    }
                                }}
                                ref={tab.key === activeKey ? selectionRef : undefined}
                            >
                                {tab.label}
                                {tab.tooltip && <IconInfo className="ml-1 text-base shrink-0" />}
                            </li>
                        </Tooltip>
                    ))}
                </ul>
            </div>
            {'content' in activeTab && (
                <div className="LemonTabs__content" key={activeKey}>
                    {activeTab.content}
                </div>
            )}
        </div>
    )
}
