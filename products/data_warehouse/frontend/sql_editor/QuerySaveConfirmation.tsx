import { RefObject } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'

export interface QuerySaveConfirmationProps {
    open: boolean
    anchor: RefObject<HTMLSpanElement>
    onClose: () => void
    onRunLatest: () => void
    onSaveAnyway: () => void
}

export function QuerySaveConfirmation({
    open,
    anchor,
    onClose,
    onRunLatest,
    onSaveAnyway,
}: QuerySaveConfirmationProps): JSX.Element {
    return (
        <Popover
            visible={open}
            referenceElement={anchor.current}
            placement="bottom-end"
            onClickOutside={onClose}
            overlay={
                <div className="max-w-80 p-2" role="dialog" aria-label="Save query without running">
                    <p>The query you’re saving has not been run successfully. Results may be from a different query.</p>
                    <div className="flex flex-wrap justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={onRunLatest}
                            data-attr="sql-editor-save-run-latest"
                        >
                            Run latest
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={onSaveAnyway}
                            data-attr="sql-editor-save-anyway"
                        >
                            Save anyway
                        </LemonButton>
                    </div>
                </div>
            }
        />
    )
}
