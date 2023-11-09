import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import Draggable from 'react-draggable'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { posthog } from '~/toolbar/posthog'
import { HedgehogButton } from '~/toolbar/button/HedgehogButton'

export function DraggableButton(): JSX.Element {
    const { dragPosition, theme } = useValues(toolbarButtonLogic)
    const { saveDragPosition } = useActions(toolbarButtonLogic)

    // KLUDGE: if we put theme directly on the div then
    // linting and typescript complain about it not being
    // a valid attribute. So we put it in a variable and
    // spread it in. 🤷‍
    const themeProps = { theme }

    return (
        <>
            <Draggable
                handle=".floating-toolbar-button"
                // don't allow dragging from mousedown on a button
                cancel={'.LemonButton'}
                position={dragPosition}
                onDrag={(_, { x, y }) => {
                    saveDragPosition(x, y)
                }}
                onStop={(_, { x, y }) => {
                    posthog.capture('toolbar dragged', { x, y })
                    saveDragPosition(x, y)
                }}
            >
                {/*theme attribute and class posthog-3000 are set here
                so that everything inside is styled correctly
                without affecting hedgehog mode */}
                <div id="button-toolbar" className="ph-no-capture posthog-3000" {...themeProps}>
                    <ToolbarButton />
                </div>
            </Draggable>
            <HedgehogButton />
        </>
    )
}
