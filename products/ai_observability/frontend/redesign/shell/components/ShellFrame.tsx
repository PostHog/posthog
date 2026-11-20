import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    SHELL_TABS,
    ShellLocation,
    ShellScope,
    ShellTabId,
    shellDocsUrl,
    shellHref,
    shellTab,
    shellTabPath,
} from '../shellNavigation'
import { ScopeSwitch } from './ScopeSwitch'

const NO_TAB = 'none'

export interface ShellFrameProps {
    location: ShellLocation
    /** Search params carried on every tab link. */
    linkParams: Record<string, unknown>
    /** Whether the project has sessions, which decides where Activity opens. Null until known. */
    hasSessions: boolean | null
    todayRailNav: boolean
    onScopeChange: (scope: ShellScope) => void
    children: React.ReactNode
}

export function ShellFrame({
    location,
    linkParams,
    hasSessions,
    todayRailNav,
    onScopeChange,
    children,
}: ShellFrameProps): JSX.Element {
    const scene = sceneConfigurations[Scene.AIObservability]
    const tab = shellTab(location.tab)
    const docsUrl = shellDocsUrl(location)

    return (
        <SceneContent>
            <SceneTitleSection
                name={scene.name}
                description={tab?.description ?? scene.description}
                resourceType={{ type: scene.iconType || 'default_icon_type' }}
                actions={
                    todayRailNav ? (
                        <Button variant="outline" render={<LinkPrimitive to={docsUrl} target="_blank" />}>
                            Documentation
                        </Button>
                    ) : (
                        <LemonButton to={docsUrl} type="secondary" targetBlank size="small">
                            Documentation
                        </LemonButton>
                    )
                }
            />
            <LemonTabs<ShellTabId | typeof NO_TAB>
                // The tab bar moves its underline only when it can measure a selected tab, so it starts over when
                // the route reaches a page with no tab. Without this the underline stays under the previous tab.
                key={location.tab ? 'tabbed' : 'untabbed'}
                activeKey={location.tab ?? NO_TAB}
                // pinned: autocapture dashboards and tests select the tab bar and its tabs by these values
                data-attr="ai-observability-tabs"
                sceneInset
                tabs={SHELL_TABS.map((entry) => ({
                    key: entry.id,
                    label: entry.label,
                    link: shellHref(shellTabPath(entry, hasSessions), linkParams),
                    'data-attr': `ai-observability-tab-${entry.id}`,
                }))}
            />
            {tab && tab.scopes.length > 0 && (
                <ScopeSwitch scopes={tab.scopes} activeScope={location.scope} onScopeChange={onScopeChange} />
            )}
            {children}
        </SceneContent>
    )
}
