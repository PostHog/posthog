import { IconPlayFilled } from '@posthog/icons'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene } from 'scenes/sceneTypes'

import { RunButtonHostProps, useRunButtonState } from './useRunButtonState'

export function RunButton({
    runQueryDisabledReason,
    scope = Scene.SQLEditor,
    ...hostProps
}: RunButtonHostProps & {
    scope?: Scene.SQLEditor | Scene.BusinessIntelligence
}): JSX.Element {
    const {
        showCancel,
        hasChangesToRun,
        tooltip,
        loading,
        showRunOptions,
        onClick,
        runAtCursor,
        runInnermostSubquery,
    } = useRunButtonState(hostProps, { allowRunOptions: scope !== Scene.BusinessIntelligence })

    return (
        <Shortcut
            name="SQLEditorRun"
            keybind={[keyBinds.run]}
            intent={showCancel ? 'Cancel query' : 'Run query'}
            interaction="click"
            scope={scope}
        >
            <LemonButton
                data-attr="sql-editor-run-button"
                onClick={onClick}
                icon={
                    showCancel ? (
                        <IconCancel />
                    ) : (
                        <IconPlayFilled color={hasChangesToRun ? 'var(--success)' : 'var(--primary)'} />
                    )
                }
                type="primary"
                size="small"
                tooltip={tooltip}
                sideAction={
                    showRunOptions
                        ? {
                              dropdown: {
                                  placement: 'bottom-end' as const,
                                  overlay: (
                                      <>
                                          <LemonButton
                                              fullWidth
                                              onClick={runAtCursor}
                                              sideIcon={<span className="text-muted text-xs">⌘↵</span>}
                                          >
                                              Run query at cursor
                                          </LemonButton>
                                          <LemonButton
                                              fullWidth
                                              onClick={runInnermostSubquery}
                                              sideIcon={<span className="text-muted text-xs">⌘⇧↵</span>}
                                          >
                                              Run innermost subquery at cursor
                                          </LemonButton>
                                      </>
                                  ),
                              },
                          }
                        : undefined
                }
                loading={loading}
                disabledReason={runQueryDisabledReason}
            >
                {showCancel ? 'Cancel' : 'Run'}
            </LemonButton>
        </Shortcut>
    )
}
