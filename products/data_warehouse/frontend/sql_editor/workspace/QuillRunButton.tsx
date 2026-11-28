import { IconChevronDown, IconPlayFilled, IconStopFilled } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Kbd,
    KbdGroup,
} from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { RunButtonHostProps, useRunButtonState } from 'scenes/data-warehouse/editor/useRunButtonState'
import { Scene } from 'scenes/sceneTypes'

/** The SQL editor's run button, and the scene's only primary action. */
export function QuillRunButton({ runQueryDisabledReason, ...hostProps }: RunButtonHostProps): JSX.Element {
    const { showCancel, tooltip, loading, showRunOptions, onClick, runAtCursor, runInnermostSubquery } =
        useRunButtonState(hostProps)

    const button = (
        <Shortcut
            name="SQLEditorRun"
            keybind={[keyBinds.run]}
            intent={showCancel ? 'Cancel query' : 'Run query'}
            interaction="click"
            scope={Scene.SQLEditor}
        >
            <Button
                variant={showCancel ? 'outline' : 'primary'}
                onClick={onClick}
                loading={loading}
                tooltip={tooltip}
                disabledReason={runQueryDisabledReason}
                data-attr="sql-editor-run-button"
            >
                {showCancel ? <IconStopFilled /> : <IconPlayFilled />}
                {showCancel ? 'Cancel' : 'Run'}
                {!showCancel ? (
                    <KbdGroup aria-hidden="true">
                        <Kbd>⌘</Kbd>
                        <Kbd>↵</Kbd>
                    </KbdGroup>
                ) : null}
            </Button>
        </Shortcut>
    )

    if (!showRunOptions) {
        return button
    }

    return (
        <DropdownMenu>
            <ButtonGroup>
                {button}
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="Run options"
                            tooltip="Run options"
                            disabledReason={runQueryDisabledReason}
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
            </ButtonGroup>
            <DropdownMenuContent align="start">
                <DropdownMenuGroup>
                    <DropdownMenuItem onClick={runAtCursor}>
                        Run query at cursor
                        <KbdGroup className="ml-auto">
                            <Kbd>⌘</Kbd>
                            <Kbd>↵</Kbd>
                        </KbdGroup>
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={runInnermostSubquery}>
                        Run innermost subquery at cursor
                        <KbdGroup className="ml-auto">
                            <Kbd>⌘</Kbd>
                            <Kbd>⇧</Kbd>
                            <Kbd>↵</Kbd>
                        </KbdGroup>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
