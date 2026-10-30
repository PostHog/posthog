import { useActions, useValues } from 'kea'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TicketMacroApi } from 'products/conversations/frontend/generated/api.schemas'

import { MacroFormModal } from '../../components/Macros/MacroFormModal'
import { supportMacrosLogic } from '../../components/Macros/supportMacrosLogic'

export function MacrosSection(): JSX.Element {
    const { macrosSorted, macrosLoading } = useValues(supportMacrosLogic)
    const { openMacroDraft, deleteMacro } = useActions(supportMacrosLogic)

    const columns: LemonTableColumns<TicketMacroApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, macro) => <span className="truncate">{macro.name}</span>,
        },
        {
            title: 'Shortcut',
            dataIndex: 'shortcut',
            render: (_, macro) => (macro.shortcut ? `/${macro.shortcut}` : ''),
        },
        {
            title: 'Uses',
            dataIndex: 'usage_count',
            align: 'right',
        },
        {
            title: 'Last used',
            dataIndex: 'last_used_at',
            render: (_, macro) => (macro.last_used_at ? <TZLabel time={macro.last_used_at} /> : 'Never'),
        },
        {
            title: '',
            width: 80,
            render: (_, macro) => (
                <div className="flex justify-end gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit"
                        onClick={() => openMacroDraft(macro)}
                    />
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete"
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Delete this macro?',
                                description: 'People on your team will no longer be able to insert it.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteMacro(macro.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="mb-0 text-sm text-muted">
                    Save replies you send often. Insert one from a ticket, or type / and its shortcut.
                </p>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => openMacroDraft(null)}
                    data-attr="support-macro-create"
                >
                    New macro
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                dataSource={macrosSorted}
                loading={macrosLoading}
                rowKey="id"
                emptyState="No macros yet"
                nouns={['macro', 'macros']}
            />
            <MacroFormModal />
        </div>
    )
}
