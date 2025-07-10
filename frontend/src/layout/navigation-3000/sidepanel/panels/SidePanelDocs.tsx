import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconExternal, IconHome } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { themeLogic } from '../../themeLogic'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelDocsLogic } from './sidePanelDocsLogic'

export function SidePanelDocsSkeleton(): JSX.Element {
    return (
        <div className="deprecated-space-y-2 absolute inset-0 p-4">
            <LemonSkeleton className="mb-12 h-10 w-full" />
            <LemonSkeleton className="h-8 w-1/3" />
            <LemonSkeleton className="mb-10 h-4 w-1/2" />
            <LemonSkeleton className="h-4 w-full" />
            <LemonSkeleton className="h-4 w-full opacity-80" />
            <LemonSkeleton className="h-4 w-full opacity-60" />
            <LemonSkeleton className="h-4 w-full opacity-40" />
            <LemonSkeleton className="h-4 w-1/2 opacity-20" />
        </div>
    )
}

export const SidePanelDocs = (): JSX.Element => {
    const ref = useRef<HTMLIFrameElement | null>(null)
    const logic = sidePanelDocsLogic({ iframeRef: ref })

    const { iframeSrc, iframeReady, currentUrl, activeMenuName, menuOptions } = useValues(logic)
    const { navigateToPage, unmountIframe, closeSidePanel } = useActions(logic)
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        ref.current?.contentWindow?.postMessage(
            {
                type: 'theme-toggle',
                isDarkModeOn,
            },
            '*'
        )
    }, [isDarkModeOn, ref.current])

    useEffect(() => {
        window.addEventListener('beforeunload', unmountIframe)

        return () => {
            window.removeEventListener('beforeunload', unmountIframe)
            unmountIframe()
        }
    }, [])

    return (
        <>
            <SidePanelPaneHeader>
                <LemonButton
                    size="small"
                    sideIcon={<IconHome />}
                    type="secondary"
                    onClick={() => {
                        ref.current?.contentWindow?.postMessage(
                            {
                                type: 'navigate',
                                url: '/docs',
                            },
                            '*'
                        )
                    }}
                />

                {menuOptions && (
                    <LemonSelect
                        placeholder="Navigate"
                        dropdownMatchSelectWidth={false}
                        onChange={navigateToPage}
                        size="small"
                        value={activeMenuName ?? ''}
                        options={menuOptions.map(({ name, url }) => ({ label: name, value: url }))}
                        className="shrink overflow-hidden whitespace-nowrap"
                    />
                )}

                <div className="flex-1" />
                <LemonButton
                    size="small"
                    sideIcon={<IconExternal />}
                    targetBlank
                    // We can't use the normal `to` property as that is intercepted to open this panel :D
                    onClick={() => {
                        window.open(currentUrl, '_blank')?.focus()
                        closeSidePanel()
                    }}
                >
                    Open in new tab
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="relative flex-1 overflow-hidden">
                <iframe
                    src={iframeSrc}
                    title="Docs"
                    className={clsx('h-full w-full', !iframeReady && 'hidden')}
                    ref={ref}
                />

                {!iframeReady && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
