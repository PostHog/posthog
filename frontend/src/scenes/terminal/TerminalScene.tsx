import { useValues } from 'kea'

import { IconTerminal } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalView } from './TerminalView'

export const scene: SceneExport = { component: TerminalScene, logic: terminalLogic }
export function TerminalScene(): JSX.Element {
    const { terminalEnabled } = useValues(terminalDockLogic)
    return (
        <SceneContent className="h-full min-h-0 flex-1 pb-1">
            <SceneTitleSection name="Terminal" resourceType={{ type: 'terminal', forceIcon: <IconTerminal /> }} />
            {terminalEnabled ? (
                <TerminalView />
            ) : (
                <LemonBanner type="info">The terminal experiment is not enabled for this project.</LemonBanner>
            )}
        </SceneContent>
    )
}
