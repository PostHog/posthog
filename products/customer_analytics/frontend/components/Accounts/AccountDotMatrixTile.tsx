import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'
import { DotMatrixDemoTooltip } from 'lib/components/DotMatrix/DotMatrixDemoTooltip'
import type { DotMatrixMockDatasetName } from 'lib/components/DotMatrix/mocks'
import { Popover } from 'lib/lemon-ui/Popover'

import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'

export function AccountDotMatrixTile({
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountViewTileLogicProps): JSX.Element {
    const generatedId = useId()
    const logic = accountDotMatrixTileLogic({
        instanceId: `${instanceId ?? 'tile'}:${generatedId}`,
        initialConfig,
        onConfigChange,
    })
    const { config, dataset, presentation } = useValues(logic)
    const { setDataset, setMode, setSelectedSeries } = useActions(logic)
    const [settingsOpen, setSettingsOpen] = useState(false)

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="account-dot-matrix-tile">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-secondary">Example data</span>
                <Popover
                    visible={settingsOpen}
                    onClickOutside={() => setSettingsOpen(false)}
                    overlay={
                        <div className="flex flex-col gap-3 p-3 w-64">
                            <LemonLabel htmlFor={`${generatedId}-dataset`}>Dataset</LemonLabel>
                            <LemonSelect<DotMatrixMockDatasetName>
                                id={`${generatedId}-dataset`}
                                value={config.dataset}
                                onChange={setDataset}
                                options={[
                                    { value: 'people', label: 'People activity' },
                                    { value: 'product_activity', label: 'Product activity' },
                                    { value: 'ci', label: 'CI health' },
                                ]}
                                fullWidth
                                aria-label="Dot matrix dataset"
                                data-attr="account-dot-matrix-dataset"
                            />
                            <LemonLabel htmlFor={`${generatedId}-mode`}>Display</LemonLabel>
                            <LemonSelect<'dots' | 'count'>
                                id={`${generatedId}-mode`}
                                value={config.mode}
                                onChange={setMode}
                                options={[
                                    { value: 'dots', label: 'Dots' },
                                    { value: 'count', label: 'Count' },
                                ]}
                                fullWidth
                                aria-label="Dot matrix display"
                                data-attr="account-dot-matrix-mode"
                            />
                        </div>
                    }
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconGear />}
                        onClick={() => setSettingsOpen((open) => !open)}
                        aria-expanded={settingsOpen}
                        data-attr="account-dot-matrix-settings"
                    >
                        Settings
                    </LemonButton>
                </Popover>
            </div>
            <DotMatrix
                {...dataset}
                {...presentation}
                mode={config.mode}
                selectedSeries={config.selectedSeries}
                onSelectedSeriesChange={setSelectedSeries}
                renderTooltip={
                    config.dataset === 'ci'
                        ? undefined
                        : (cell) => (
                              <DotMatrixDemoTooltip
                                  cell={cell}
                                  selectedSeries={config.selectedSeries}
                                  datasetName={config.dataset}
                              />
                          )
                }
            />
        </div>
    )
}
