import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { HedgehogOptions } from 'lib/components/HedgehogBuddy/HedgehogOptions'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { toolbarLogic } from '../bar/toolbarLogic'

export const HedgehogMenu = (): JSX.Element => {
    const { setHedgehogMode, setVisibleMenu } = useActions(toolbarLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <div className="p-1">
                    <HedgehogOptions />
                </div>
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer>
                <div className="flex gap-2 justify-between flex-1">
                    <LemonButton type="secondary" size="small" onClick={() => setHedgehogMode(false)}>
                        Go away...
                    </LemonButton>
                    <LemonButton type="primary" size="small" onClick={() => setVisibleMenu('none')}>
                        Carry on!
                    </LemonButton>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
