import { useValues } from 'kea'

import { IconTerminal } from '@posthog/icons'

import { NotFound } from 'lib/components/NotFound'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalView } from './TerminalView'

export const scene: SceneExport = { component: TerminalScene, logic: terminalLogic }
export function TerminalScene(): JSX.Element {
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    const { terminalEnabled } = useValues(terminalDockLogic)
    if (receivedFeatureFlags && !terminalEnabled) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent className="h-full min-h-0 flex-1 pb-1">
            <SceneTitleSection name="Terminal" resourceType={{ type: 'terminal', forceIcon: <IconTerminal /> }} />
            {terminalEnabled && <TerminalView />}
        </SceneContent>
    )
}
