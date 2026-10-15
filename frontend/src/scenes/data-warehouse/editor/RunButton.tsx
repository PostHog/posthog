import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlayFilled } from '@posthog/icons'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene } from 'scenes/sceneTypes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

export function RunButton({
    onRunQuery,
    runQueryLoading,
    runQueryDisabledReason,
    runQueryTooltip,
    onCancelQuery,
    cancelQueryLoading,
    scope = Scene.SQLEditor,
}: {
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
    scope?: Scene.SQLEditor | Scene.BusinessIntelligence
}): JSX.Element {
    const { runQuery, runSubquery } = useActions(sqlEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { metadata, queryInput, isSourceQueryLastRun } = useValues(sqlEditorLogic)

    const isRunning = onRunQuery ? !!runQueryLoading : responseLoading
    // The external-run path shows a cancel affordance only when a canceller is provided.
    const showCancel = isRunning && (!onRunQuery || !!onCancelQuery)

    const [iconColor, tooltipContent] = useMemo(() => {
        if (onRunQuery) {
            if (isRunning && onCancelQuery) {
                return ['var(--success)', 'Stop the running query']
            }
            return ['var(--success)', runQueryTooltip ?? 'Run query']
        }

        if (isSourceQueryLastRun) {
            return ['var(--primary)', 'No changes to run']
        }

        // No index verdict colors this button. The per-filter report counts filters, and a count does
        // not track what a query costs: one selective filter bounds the read however many others scan,
        // and nothing here yet looks at the time range, which is what really decides how much is read.
        return ['var(--success)', 'New changes to run']
    }, [metadata, queryInput, isSourceQueryLastRun, onRunQuery, runQueryTooltip, isRunning, onCancelQuery])

    const sideAction = useMemo(
        () =>
            responseLoading || onRunQuery || scope === Scene.BusinessIntelligence
                ? undefined
                : {
                      dropdown: {
                          placement: 'bottom-end' as const,
                          overlay: (
                              <>
                                  <LemonButton
                                      fullWidth
                                      onClick={() => runQuery()}
                                      sideIcon={<span className="text-muted text-xs">⌘↵</span>}
                                  >
                                      Run query at cursor
                                  </LemonButton>
                                  <LemonButton
                                      fullWidth
                                      onClick={() => runSubquery()}
                                      sideIcon={<span className="text-muted text-xs">⌘⇧↵</span>}
                                  >
                                      Run innermost subquery at cursor
                                  </LemonButton>
                              </>
                          ),
                      },
                  },
        [onRunQuery, responseLoading, runQuery, runSubquery, scope]
    )

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
                onClick={() => {
                    if (onRunQuery) {
                        if (runQueryLoading) {
                            // Guard against double submission: one cancel request at a time.
                            if (onCancelQuery && !cancelQueryLoading) {
                                onCancelQuery()
                            }
                        } else {
                            onRunQuery()
                        }
                    } else if (responseLoading) {
                        cancelQuery()
                    } else {
                        runQuery()
                    }
                }}
                icon={showCancel ? <IconCancel /> : <IconPlayFilled color={iconColor} />}
                type="primary"
                size="small"
                tooltip={tooltipContent}
                sideAction={sideAction}
                loading={onRunQuery ? (onCancelQuery ? !!cancelQueryLoading : isRunning) : false}
                disabledReason={runQueryDisabledReason}
            >
                {showCancel ? 'Cancel' : 'Run'}
            </LemonButton>
        </Shortcut>
    )
}
