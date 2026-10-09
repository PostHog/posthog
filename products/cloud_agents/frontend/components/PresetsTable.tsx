import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { CloudAgentPresetApi } from '../generated/api.schemas'
import { cloudAgentPresetsLogic } from '../logics/cloudAgentPresetsLogic'
import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { formatBoxSize, formatRate } from '../utils/pricing'
import { INFERENCE_MODE_DISPLAY } from '../utils/runStatus'

export function PresetsTable(): JSX.Element {
    const { presets, presetsLoading, deletingPresetId } = useValues(cloudAgentPresetsLogic)
    const { deletePreset } = useActions(cloudAgentPresetsLogic)
    const { sizes } = useValues(cloudAgentsCatalogLogic)

    const columns: LemonTableColumns<CloudAgentPresetApi> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, preset) => (
                <div className="flex flex-col">
                    <Link
                        to={urls.cloudAgentPreset(preset.id)}
                        className="font-semibold"
                        data-attr="cloud-agents-preset-link"
                    >
                        {preset.name}
                    </Link>
                    {preset.description && (
                        <span className="text-secondary text-xs line-clamp-1 max-w-100">{preset.description}</span>
                    )}
                </div>
            ),
        },
        {
            title: 'Repository',
            key: 'repository',
            render: (_, preset) =>
                preset.repositories?.[0] ? (
                    <span className="whitespace-nowrap" translate="no">
                        {preset.repositories[0].name}
                    </span>
                ) : (
                    <span className="text-secondary">Team default</span>
                ),
        },
        {
            title: 'Box size',
            key: 'size',
            render: (_, preset) => {
                const size = sizes.find((candidate) => candidate.name === preset.size)
                return size ? (
                    <div className="flex flex-col whitespace-nowrap" translate="no">
                        <span>{formatBoxSize(size)}</span>
                        <span className="text-secondary text-xs">{formatRate(size.price_per_hour_usd)} per hour</span>
                    </div>
                ) : (
                    <span className="text-secondary">Team default</span>
                )
            },
        },
        {
            title: 'Model provider',
            key: 'inference',
            render: (_, preset) =>
                preset.inference ? (
                    <span className="whitespace-nowrap">{INFERENCE_MODE_DISPLAY[preset.inference]?.label}</span>
                ) : (
                    <span className="text-secondary">Team default</span>
                ),
        },
        {
            title: 'Updated',
            key: 'updated_at',
            render: (_, preset) => <TZLabel time={preset.updated_at} />,
        },
        {
            key: 'actions',
            width: 0,
            render: (_, preset) => (
                <LemonButton
                    size="small"
                    status="danger"
                    icon={<IconTrash />}
                    tooltip="Delete preset"
                    loading={deletingPresetId === preset.id}
                    disabledReason={deletingPresetId ? 'Deleting a preset' : undefined}
                    onClick={() =>
                        LemonDialog.open({
                            title: `Delete the preset "${preset.name}"?`,
                            description:
                                'API calls that name this preset stop working. Runs that used it stay in the list.',
                            primaryButton: {
                                children: 'Delete preset',
                                status: 'danger',
                                onClick: () => deletePreset(preset),
                                'data-attr': 'cloud-agents-preset-delete-confirm',
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
                    data-attr="cloud-agents-preset-delete"
                />
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={presets ?? []}
            columns={columns}
            rowKey="id"
            loading={presetsLoading}
            emptyState={
                <div className="flex flex-col items-center gap-2 py-6 text-center">
                    <span className="font-semibold">No presets yet</span>
                    <span className="text-secondary max-w-120">
                        A preset saves a repository, a box size and instructions under one name. Then an API call needs
                        only the preset name and a prompt.
                    </span>
                    <LemonButton
                        type="primary"
                        to={urls.cloudAgentPreset('new')}
                        data-attr="cloud-agents-preset-empty-new"
                    >
                        Create a preset
                    </LemonButton>
                </div>
            }
            data-attr="cloud-agents-presets-table"
        />
    )
}
