import { useActions, useValues } from 'kea'

import { IconCopy, IconCursorClick, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { extensionPageToolsLogic } from './extensionPageToolsLogic'

export function ExtensionElementSelector(): JSX.Element {
    const { selectedElementForPage, contentStatus, contentStatusLoading } = useValues(extensionPageToolsLogic)
    const { startElementSelection, copySelector, clearSelectedElement } = useActions(extensionPageToolsLogic)
    const actionStep = selectedElementForPage?.actionStep

    return (
        <div className="flex flex-col gap-1">
            <LemonButton
                fullWidth
                type="secondary"
                size="small"
                icon={<IconCursorClick />}
                loading={contentStatusLoading}
                disabledReason={contentStatus.selecting ? 'Selection is on. Click an element on the page.' : null}
                tooltip="Pick an element on the page to use in an action"
                onClick={startElementSelection}
                data-attr="toolbar-extension-select-element"
            >
                Select an element
            </LemonButton>
            {actionStep && (
                <div className="flex flex-col gap-1 border rounded p-2 text-xs">
                    <div className="flex items-start gap-1">
                        <code className="flex-1 break-all" translate="no">
                            {actionStep.selector || 'No selector found for this element'}
                        </code>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="Copy selector"
                            disabledReason={actionStep.selector ? null : 'No selector to copy'}
                            onClick={copySelector}
                            data-attr="toolbar-extension-copy-selector"
                        />
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            tooltip="Clear"
                            onClick={clearSelectedElement}
                            data-attr="toolbar-extension-clear-selection"
                        />
                    </div>
                    {actionStep.text && <div className="text-secondary truncate">Text: {actionStep.text}</div>}
                    {selectedElementForPage.selectorQuality?.isFragile && (
                        <div className="text-warning">
                            This selector can break when the page changes:{' '}
                            {selectedElementForPage.selectorQuality.reason?.toLowerCase()}.
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
