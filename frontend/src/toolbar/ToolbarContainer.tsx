import { useValues } from 'kea'
import { toolbarLogic } from './toolbarLogic'
import { Elements } from './elements/Elements'
import { Fade } from 'lib/components/Fade/Fade'
import { toolbarButtonLogic } from './bar/toolbarButtonLogic'
import { HedgehogButton } from './bar/HedgehogButton'
import { Toolbar } from './bar/Toolbar'

export function ToolbarContainer(): JSX.Element {
    const { buttonVisible } = useValues(toolbarLogic)
    const { theme } = useValues(toolbarButtonLogic)

    // KLUDGE: if we put theme directly on the div then
    // linting and typescript complain about it not being
    // a valid attribute. So we put it in a variable and
    // spread it in. 🤷‍
    const themeProps = { theme }

    return (
        <Fade visible={buttonVisible} className="toolbar-global-fade-container ph-no-capture posthog-3000">
            <Elements />
            <div id="button-toolbar" className="ph-no-capture posthog-3000" {...themeProps}>
                <Toolbar />
            </div>
            <HedgehogButton />
        </Fade>
    )
}
