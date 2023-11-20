import clsx from 'clsx'
import React from 'react'
import { useSliderPositioning } from 'lib/lemon-ui/hooks'

const TRANSITION_MS = 200
export const WebTabs = ({
    className,
    activeTabId,
    tabs,
    setActiveTabId,
}: {
    className?: string
    activeTabId: string
    tabs: { id: string; title: string; linkText: string; content: React.ReactNode }[]
    setActiveTabId: (id: string) => void
}): JSX.Element => {
    const activeTab = tabs.find((t) => t.id === activeTabId)
    const { containerRef, selectionRef, sliderWidth, sliderOffset, transitioning } = useSliderPositioning<
        HTMLUListElement,
        HTMLLIElement
    >(activeTabId, TRANSITION_MS)

    return (
        <div className={clsx(className, 'flex flex-col')}>
            <div className="flex flex-row items-center self-stretch mb-3">
                {<h2 className="flex-1 m-0">{activeTab?.title}</h2>}
                <div className="flex flex-col items-stretch relative">
                    {tabs.length > 1 && (
                        // TODO switch to a select if more than 3
                        <ul className="flex flex-row items-center space-x-2" ref={containerRef}>
                            {tabs.map(({ id, linkText }) => (
                                <li key={id} ref={id === activeTabId ? selectionRef : undefined}>
                                    <button
                                        className={clsx(
                                            'bg-transparent border-none cursor-pointer',
                                            id === activeTabId ? 'text-bold text-link' : 'text-current hover:text-link'
                                        )}
                                        onClick={() => setActiveTabId(id)}
                                    >
                                        {linkText}
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                    <div className="w-full relative">
                        <div
                            className="h-px bg-link absolute"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: sliderWidth,
                                left: 0,
                                transform: `translateX(${sliderOffset}px)`,
                                transition: transitioning
                                    ? `width ${TRANSITION_MS}ms ease, transform ${TRANSITION_MS}ms ease`
                                    : undefined,
                            }}
                        />
                    </div>
                </div>
            </div>
            <div>{activeTab?.content}</div>
        </div>
    )
}
