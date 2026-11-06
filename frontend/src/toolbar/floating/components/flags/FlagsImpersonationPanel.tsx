import { useActions, useValues } from 'kea'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'

export interface FlagsImpersonationPanelProps {
    disabledReason: string | null
}

export function FlagsImpersonationPanel({ disabledReason }: FlagsImpersonationPanelProps): JSX.Element {
    const { impersonatedDistinctId, draftDistinctId, impersonationOpen } = useValues(flagsToolbarLogic)
    const { loadFlagsForDistinctId, clearImpersonation, setDraftDistinctId } = useActions(flagsToolbarLogic)
    const loadDraft = (): void => {
        const distinctId = draftDistinctId.trim()
        if (!disabledReason && distinctId) {
            loadFlagsForDistinctId(distinctId)
        }
    }

    return (
        <AnimatedCollapsible collapsed={!impersonationOpen && !impersonatedDistinctId}>
            <div className="pb-2">
                {impersonatedDistinctId ? (
                    <div className="flex items-center gap-2">
                        <span className="text-xs flex-1 truncate">
                            Viewing as: <strong>{impersonatedDistinctId}</strong>
                        </span>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            onClick={clearImpersonation}
                            disabledReason={disabledReason}
                        >
                            Clear
                        </LemonButton>
                    </div>
                ) : (
                    <div className="flex gap-1 items-center">
                        <LemonInput
                            placeholder="Distinct ID"
                            fullWidth
                            size="small"
                            value={draftDistinctId}
                            onChange={setDraftDistinctId}
                            onPressEnter={loadDraft}
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="flex-shrink-0"
                            onClick={loadDraft}
                            disabledReason={
                                disabledReason ?? (!draftDistinctId.trim() ? 'Enter a distinct ID' : undefined)
                            }
                        >
                            Load
                        </LemonButton>
                    </div>
                )}
            </div>
        </AnimatedCollapsible>
    )
}
