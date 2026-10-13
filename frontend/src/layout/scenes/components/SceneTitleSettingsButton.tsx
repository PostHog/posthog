import posthog from 'posthog-js'
import { useContext } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SceneContentContext } from './SceneContent'
import { getSceneSettingsUrl } from './sceneSettingsUrl'

export function SceneTitleSettingsButton(): JSX.Element | null {
    const { productKey } = useContext(SceneContentContext)
    const settingsUrl = getSceneSettingsUrl(productKey)

    if (!settingsUrl) {
        return null
    }

    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        size="icon"
                        aria-label="Settings"
                        data-attr="scene-title-settings"
                        onClick={() => posthog.capture('scene title settings clicked', { product: productKey })}
                        render={<LinkPrimitive to={settingsUrl} />}
                    />
                }
            >
                <IconGear />
            </TooltipTrigger>
            <TooltipContent>Settings</TooltipContent>
        </Tooltip>
    )
}
