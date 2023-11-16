import { useValues } from 'kea'
import { toolbarLogic } from './toolbarLogic'
import { Elements } from './elements/Elements'
import { Fade } from 'lib/components/Fade/Fade'
import { toolbarButtonLogic } from './button/toolbarButtonLogic'
import { HedgehogButton } from './button/HedgehogButton'
import { Toolbar3000 } from './button/Toolbar3000'

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
                <Toolbar3000 />
            </div>
            <HedgehogButton />
        </Fade>
    )
}
