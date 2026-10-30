import './Navigation.scss'

import { useMountedLogic, useValues } from 'kea'
import { ReactNode, useLayoutEffect } from 'react'

import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { todayPanelChatSessionLogic } from '~/layout/today/todayPanelChatSessionLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { BareLayout } from './layout-modes/BareLayout'
import { ClassicLayout } from './layout-modes/ClassicLayout'
import { EmbeddedLayout } from './layout-modes/EmbeddedLayout'
import { MinimalLayout } from './layout-modes/MinimalLayout'
import { TodayFramedLayout } from './layout-modes/TodayFramedLayout'
import { TodayPhoneLayout } from './layout-modes/TodayPhoneLayout'
import { resolveLayoutMode } from './layoutMode'
import { navigation3000Logic } from './navigationLogic'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    useMountedLogic(maxGlobalLogic)
    useMountedLogic(mcpHintLogic)

    const { mode } = useValues(navigation3000Logic)
    const { todayRailEnabled: todayRail, phoneLayout } = useValues(todayShellLogic)

    // Runs before scene effects, so a scene cannot clear the restored chat. TodayShell is lazy, so mount it here.
    useLayoutEffect(() => (todayRail ? todayPanelChatSessionLogic.mount() : undefined), [todayRail])

    /**
     * 'Today' is the new scene shell for PostHog.
     *
     * Controlled under 'today-rail-nav' flag.
     */

    const todayPhoneBodyClass = todayRail && phoneLayout && mode === 'full'

    useLayoutEffect(() => {
        if (!todayPhoneBodyClass) {
            return
        }

        document.body.classList.add('has-today-phone-layout')

        return () => document.body.classList.remove('has-today-phone-layout')
    }, [todayPhoneBodyClass])

    const layoutMode = resolveLayoutMode({
        mode,
        todayRail,
        phoneLayout,
    })

    switch (layoutMode) {
        case 'bare':
            return <BareLayout>{children}</BareLayout>
        case 'minimal':
            return <MinimalLayout sceneConfig={sceneConfig}>{children}</MinimalLayout>
        case 'embedded':
            return <EmbeddedLayout>{children}</EmbeddedLayout>
        case 'classic':
            return <ClassicLayout sceneConfig={sceneConfig}>{children}</ClassicLayout>
        case 'today-framed':
            return <TodayFramedLayout sceneConfig={sceneConfig}>{children}</TodayFramedLayout>
        case 'today-phone':
            return <TodayPhoneLayout sceneConfig={sceneConfig}>{children}</TodayPhoneLayout>
    }
}
