import { useActions, useValues } from 'kea'

import { IconCopy, IconCursorClick, IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { isDevtoolsPanel } from './extensionBrowser'
import { extensionPageToolsLogic } from './extensionPageToolsLogic'

export function ExtensionElementSelector(): JSX.Element {
    const { selectedElementForPage, contentStatus, contentStatusLoading, user } = useValues(extensionPageToolsLogic)
    const { startElementSelection, selectInspectedElement, copySelector, clearSelectedElement, createAction } =
        useActions(extensionPageToolsLogic)
    const actionStep = selectedElementForPage?.actionStep

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap gap-1">
                <LemonButton
                    className="flex-1"
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
                {isDevtoolsPanel() && (
                    <LemonButton
                        className="flex-1"
                        type="secondary"
                        size="small"
                        icon={<IconSearch />}
                        loading={contentStatusLoading}
                        tooltip="Use the element selected in the Elements panel ($0)"
                        onClick={selectInspectedElement}
                        data-attr="toolbar-extension-use-inspected-element"
                    >
                        Use inspected element
                    </LemonButton>
                )}
            </div>
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
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlusSmall />}
                        disabledReason={user ? null : 'Checking your project…'}
                        onClick={createAction}
                        data-attr="toolbar-extension-create-action"
                    >
                        Create action
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
