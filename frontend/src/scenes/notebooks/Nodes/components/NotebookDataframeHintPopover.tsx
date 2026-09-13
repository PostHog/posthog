import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'

import { notebookDataframeHintLogic } from './notebookDataframeHintLogic'

export function NotebookDataframeHintPopover({
    nodeId,
    notebookShortId,
    referenceElement,
}: {
    nodeId: string
    notebookShortId: string
    referenceElement: HTMLElement | null
}): JSX.Element {
    const logic = notebookDataframeHintLogic({ shortId: notebookShortId })
    const { hintNodeId } = useValues(logic)
    const { dismissHint } = useActions(logic)

    return (
        <Popover
            visible={hintNodeId === nodeId && !!referenceElement}
            referenceElement={referenceElement}
            placement="top-start"
            onClickOutside={dismissHint}
            overlay={
                <div className="flex max-w-80 flex-col gap-2">
                    <p className="m-0 font-semibold">Name this output to reuse it</p>
                    <p className="m-0 text-muted">
                        A named output becomes a dataframe later cells can read. SQL reads it as a table name. Python
                        reads it as a variable.
                    </p>
                    <LemonButton
                        type="primary"
                        size="small"
                        className="self-start"
                        data-attr="notebook-dataframe-hint-dismiss"
                        onClick={dismissHint}
                    >
                        Got it
                    </LemonButton>
                </div>
            }
        />
    )
}
