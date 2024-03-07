import { IconExternal, IconHome } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { themeLogic } from '../../themeLogic'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelDocsLogic } from './sidePanelDocsLogic'

export function SidePanelDocsSkeleton(): JSX.Element {
    return (
        <div className="absolute inset-0 p-4 space-y-2">
            <LemonSkeleton className="w-full h-10 mb-12" />
            <LemonSkeleton className="w-1/3 h-8" />
            <LemonSkeleton className="w-1/2 h-4 mb-10" />
            <LemonSkeleton className="w-full h-4" />
            <LemonSkeleton className="w-full h-4 opacity-80" />
            <LemonSkeleton className="w-full h-4 opacity-60" />
            <LemonSkeleton className="w-full h-4 opacity-40" />
            <LemonSkeleton className="w-1/2 h-4 opacity-20" />
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
                    className={clsx('w-full h-full', !iframeReady && 'hidden')}
                    ref={ref}
                />

                {!iframeReady && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
