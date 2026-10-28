import { useValues } from 'kea'
import { createPortal } from 'react-dom'

import { ElementHighlight } from '~/toolbar/product-tours/ElementHighlight'

import { INTERNAL_FEEDBACK_IGNORE_ATTR } from './captureFeedbackScreenshot'
import { InternalFeedbackBar } from './InternalFeedbackBar'
import { internalFeedbackLogic } from './internalFeedbackLogic'
import { InternalFeedbackPopover } from './InternalFeedbackPopover'

/**
 * Staff-only bar for pointing at an element and sending feedback about it to Slack.
 * It renders in a portal on <body>, next to the portals of menus and modals, so it can stay
 * above them and keep working while one of them is open.
 */
export function InternalFeedbackWidget(): JSX.Element | null {
    const { isHidden, isInspecting, hoverElementRect, selectedElementRect } = useValues(internalFeedbackLogic)

    if (isHidden) {
        return null
    }

    return createPortal(
        <>
            <div {...{ [INTERNAL_FEEDBACK_IGNORE_ATTR]: '' }} className="contents">
                {selectedElementRect && <ElementHighlight rect={selectedElementRect} isSelected />}
                {isInspecting && hoverElementRect && <ElementHighlight rect={hoverElementRect} />}
            </div>
            <InternalFeedbackPopover />
            <InternalFeedbackBar />
        </>,
        document.body
    )
}
