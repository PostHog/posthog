import { IconExternal, IconHome } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { themeLogic } from '../../themeLogic'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { POSTHOG_WEBSITE_ORIGIN, sidePanelDocsLogic } from './sidePanelDocsLogic'

type Menu = {
    name: string
    url?: string
}

function SidePanelDocsSkeleton(): JSX.Element {
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
    const { iframeSrc, currentUrl } = useValues(sidePanelDocsLogic)
    const { updatePath, unmountIframe, closeSidePanel, handleExternalUrl } = useActions(sidePanelDocsLogic)
    const ref = useRef<HTMLIFrameElement>(null)
    const [ready, setReady] = useState(false)
    const { isDarkModeOn } = useValues(themeLogic)
    const [menu, setMenu] = useState<Menu[] | null>(null)
    const [activeMenuName, setActiveMenuName] = useState<string | null>(null)

    const handleMenuChange = (newValue: string | null): void => {
        const url = menu?.find(({ name }: Menu) => name === newValue)?.url
        if (url) {
            ref.current?.contentWindow?.postMessage(
                {
                    type: 'navigate',
                    url,
                },
                '*'
            )
        }
    }

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
        const onMessage = (event: MessageEvent): void => {
            if (event.origin === POSTHOG_WEBSITE_ORIGIN) {
                if (event.data.type === 'internal-navigation') {
                    updatePath(event.data.url)
                    return
                }
                if (event.data.type === 'docs-ready') {
                    setReady(true)
                    return
                }

                if (event.data.type === 'external-navigation') {
                    // This should only be triggered for app|eu.posthog.com links
                    handleExternalUrl(event.data.url)
                    return
                }
                if (event.data.type === 'docs-menu') {
                    setMenu(event.data.menu)
                    return
                }

                if (event.data.type === 'docs-active-menu') {
                    setActiveMenuName(event.data.activeMenuName)
                    return
                }

                console.warn('Unhandled iframe message from Docs:', event.data)
            }
        }

        window.addEventListener('message', onMessage)

        return () => window.removeEventListener('message', onMessage)
    }, [ref.current])

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

                {menu && (
                    <LemonSelect
                        placeholder="Navigate"
                        dropdownMatchSelectWidth={false}
                        onChange={handleMenuChange}
                        size="small"
                        value={activeMenuName}
                        options={menu.map(({ name }) => ({ label: name, value: name }))}
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
                <iframe src={iframeSrc} title="Docs" className={clsx('w-full h-full', !ready && 'hidden')} ref={ref} />

                {!ready && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
