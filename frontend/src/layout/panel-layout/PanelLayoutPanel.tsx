import { IconPin, IconPinFilled, IconSearch, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { useRef } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { ProjectDropdownMenu } from './ProjectDropdownMenu'

interface PanelLayoutPanelProps {
    searchPlaceholder?: string
    panelActions?: React.ReactNode
    children: React.ReactNode
}

export function PanelLayoutPanel({ searchPlaceholder, panelActions, children }: PanelLayoutPanelProps): JSX.Element {
    const { clearSearch, setSearchTerm, toggleLayoutPanelPinned } = useActions(panelLayoutLogic)
    const { isLayoutPanelPinned, searchTerm, panelTreeRef } = useValues(panelLayoutLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)

    return (
        <>
            <nav
                className={clsx('flex flex-col max-h-screen min-h-screen relative w-[320px] border-r border-primary')}
                ref={containerRef}
            >
                <div className="flex justify-between p-1 bg-surface-tertiary">
                    <ProjectDropdownMenu />
                    <div className="flex gap-1 items-center justify-end">
                        {!isMobileLayout && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                tooltip={isLayoutPanelPinned ? 'Unpin panel' : 'Pin panel'}
                                onClick={() => toggleLayoutPanelPinned(!isLayoutPanelPinned)}
                                className="hover:bg-fill-highlight-100 shrink-0"
                                icon={
                                    isLayoutPanelPinned ? (
                                        <IconWrapper>
                                            <IconPinFilled />
                                        </IconWrapper>
                                    ) : (
                                        <IconWrapper>
                                            <IconPin />
                                        </IconWrapper>
                                    )
                                }
                            />
                        )}

                        {panelActions ?? null}
                    </div>
                </div>
                <div className="border-b border-secondary h-px" />
                <div className="z-main-nav flex flex-1 flex-col justify-between overflow-y-auto bg-surface-secondary">
                    <div className="flex gap-1 p-1 items-center justify-between">
                        <LemonInput
                            placeholder={searchPlaceholder}
                            className="w-full"
                            prefix={
                                <IconWrapper>
                                    <IconSearch />
                                </IconWrapper>
                            }
                            autoFocus
                            size="small"
                            value={searchTerm}
                            onChange={(value) => setSearchTerm(value)}
                            suffix={
                                searchTerm ? (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        onClick={() => clearSearch()}
                                        icon={
                                            <IconWrapper>
                                                <IconX />
                                            </IconWrapper>
                                        }
                                        className="bg-transparent [&_svg]:opacity-30 hover:[&_svg]:opacity-100"
                                        tooltip="Clear search"
                                    />
                                ) : null
                            }
                            onKeyDown={(e) => {
                                if (e.key === 'ArrowDown') {
                                    e.preventDefault() // Prevent scrolling
                                    const visibleItems = panelTreeRef?.current?.getVisibleItems()
                                    if (visibleItems && visibleItems.length > 0) {
                                        e.currentTarget.blur() // Remove focus from input
                                        panelTreeRef?.current?.focusItem(visibleItems[0].id)
                                    }
                                }
                            }}
                        />
                    </div>
                    <div className="border-b border-primary h-px" />
                    {children}
                </div>
            </nav>
        </>
    )
}
