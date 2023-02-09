import clsx from 'clsx'
import { useSliderPositioning } from '../hooks'
import './LemonTabs.scss'

export interface AbstractLemonTab<T extends string> {
    key: T
    label: string
}

export interface ConcreteLemonTab<T extends string> extends AbstractLemonTab<T> {
    content: JSX.Element
}

export type LemonTab<T extends string> = AbstractLemonTab<T> | ConcreteLemonTab<T>

export interface LemonTabsProps<T extends string> {
    activeKey: T
    onChange: (key: T) => void
    tabs: LemonTab<T>[]
}

interface LemonTabsCSSProperties extends React.CSSProperties {
    '--lemon-tabs-slider-width': `${number}px`
    '--lemon-tabs-slider-offset': `${number}px`
}

export function LemonTabs<T extends string>({ activeKey, onChange, tabs }: LemonTabsProps<T>): JSX.Element {
    const { containerRef, selectionRef, sliderWidth, sliderOffset } = useSliderPositioning<
        HTMLDivElement,
        HTMLLIElement
    >(activeKey)

    const activeTab = tabs.find((tab) => tab.key === activeKey)

    if (!activeTab) {
        throw new Error(`No tab found with key ${activeKey}`)
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className="LemonTabs"
            style={
                {
                    '--lemon-tabs-slider-width': `${sliderWidth}px`,
                    '--lemon-tabs-slider-offset': `${sliderOffset}px`,
                } as LemonTabsCSSProperties
            }
        >
            <div className="LemonTabs__bar" role="tablist" ref={containerRef}>
                <ul>
                    {sliderWidth > 0 && <div className="LemonTabs__slider" />}
                    {tabs.map((tab) => (
                        <li
                            key={tab.key}
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
                        </li>
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
