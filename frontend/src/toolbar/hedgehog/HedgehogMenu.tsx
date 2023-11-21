import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { HedgehogAccessories } from 'lib/components/HedgehogBuddy/HedgehogAccessories'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { toolbarLogic } from '../bar/toolbarLogic'

export const HedgehogMenu = (): JSX.Element => {
    const { setHedgehogMode, setVisibleMenu } = useActions(toolbarLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Body>
                <div className="p-1">
                    <HedgehogAccessories />
                </div>
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer>
                <div className="flex gap-2 justify-between flex-1">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            setHedgehogMode(false)
                            setVisibleMenu('none')
                        }}
                    >
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
