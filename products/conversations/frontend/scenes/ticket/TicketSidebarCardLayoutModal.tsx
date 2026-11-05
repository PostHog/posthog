import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { SIDEBAR_ROW_META, SidebarCardRowConfig } from './ticketSidebarLayout'
import { ticketSidebarLayoutLogic } from './ticketSidebarLayoutLogic'

function SidebarRowConfigItem({
    row,
    index,
    isFirst,
    isLast,
    onMove,
    onToggleVisibility,
}: {
    row: SidebarCardRowConfig
    index: number
    isFirst: boolean
    isLast: boolean
    onMove: (fromIndex: number, toIndex: number) => void
    onToggleVisibility: () => void
}): JSX.Element {
    const meta = SIDEBAR_ROW_META[row.id]

    return (
        <div
            className={`flex items-center gap-3 p-2.5 rounded border transition-colors ${
                row.visible ? 'bg-bg-light border-border' : 'bg-side border-border-light opacity-75'
            }`}
        >
            <div className="flex items-center gap-1">
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    disabledReason={isFirst ? 'Already at top' : undefined}
                    onClick={() => onMove(index, index - 1)}
                    tooltip="Move row up"
                    aria-label={`Move ${meta.label} up`}
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowDown />}
                    disabledReason={isLast ? 'Already at bottom' : undefined}
                    onClick={() => onMove(index, index + 1)}
                    tooltip="Move row down"
                    aria-label={`Move ${meta.label} down`}
                />
            </div>

            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-default">{meta.label}</span>
                    {!row.visible && (
                        <LemonTag type="muted" size="small">
                            Hidden
                        </LemonTag>
                    )}
                </div>
                <div className="text-xs text-muted truncate">{meta.description}</div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
                <LemonSwitch
                    checked={row.visible}
                    onChange={onToggleVisibility}
                    label={row.visible ? 'Visible' : 'Hidden'}
                    bordered
                />
            </div>
        </div>
    )
}

export function TicketSidebarCardLayoutModal(): JSX.Element {
    const { isLayoutModalOpen, draftLayout, hasUserOverride, isCustomized, currentTeam, user } =
        useValues(ticketSidebarLayoutLogic)
    const {
        setLayoutModalOpen,
        moveDraftRow,
        toggleDraftRowVisibility,
        saveDraftLayout,
        resetUserLayout,
        saveAsTeamDefault,
    } = useActions(ticketSidebarLayoutLogic)

    const canManageTeam = Boolean(user?.is_staff || currentTeam?.user_role === 'admin' || currentTeam?.user_role === 'owner')

    return (
        <LemonModal
            isOpen={isLayoutModalOpen}
            onClose={() => setLayoutModalOpen(false)}
            width={580}
            title="Customize ticket sidebar card"
            description="Reorder rows and hide fields you don't need to match your support workflow. Changes are saved to your browser preferences."
            footer={
                <div className="flex items-center justify-between w-full flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            onClick={resetUserLayout}
                            disabledReason={!hasUserOverride && !isCustomized ? 'Already at default layout' : undefined}
                            tooltip="Reset card rows and order to defaults"
                        >
                            Reset to default
                        </LemonButton>
                        {canManageTeam && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={saveAsTeamDefault}
                                tooltip="Save this layout as the default for all team members in this project"
                            >
                                Set as team default
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton size="small" type="secondary" onClick={() => setLayoutModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton size="small" type="primary" onClick={saveDraftLayout}>
                            Save layout
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-2 py-2 max-h-[60vh] overflow-y-auto pr-1">
                {draftLayout.map((row, index) => (
                    <SidebarRowConfigItem
                        key={row.id}
                        row={row}
                        index={index}
                        isFirst={index === 0}
                        isLast={index === draftLayout.length - 1}
                        onMove={moveDraftRow}
                        onToggleVisibility={() => toggleDraftRowVisibility(row.id)}
                    />
                ))}
            </div>
        </LemonModal>
    )
}
