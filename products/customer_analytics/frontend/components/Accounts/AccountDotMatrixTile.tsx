import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'
import { Popover } from 'lib/lemon-ui/Popover'

import type { AccountActivityMatrixResult } from '~/queries/schema/schema-general'

import type { AccountActivityMatrixDatum } from './accountActivityMatrix'
import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { DOT_MATRIX_WEEK_OPTIONS, type DotMatrixWeeks } from './dotMatrixTileConfig'

const MATRIX_PAGE_SIZE = 20

export interface AccountDotMatrixTileProps extends AccountViewTileLogicProps {
    accountId: string
}

function emptyStateMessage(result: AccountActivityMatrixResult | null, weeks: number): string {
    switch (result?.emptyReason) {
        case 'no_metrics':
            return 'Add a usage metric in project settings to see activity here.'
        case 'no_group_type':
            return 'Choose an account group type in Customer analytics settings to see activity here.'
        case 'no_external_id':
            return "This account isn't linked to any activity yet."
        default:
            return `No activity for this account in the last ${weeks} weeks.`
    }
}

export function AccountDotMatrixTile({
    accountId,
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountDotMatrixTileProps): JSX.Element {
    const generatedId = useId()
    const logic = accountDotMatrixTileLogic({
        instanceId: `${instanceId ?? 'tile'}:${generatedId}`,
        accountId,
        initialConfig,
        onConfigChange,
    })
    const { accountActivityMatrix, accountActivityMatrixLoading, config, loadFailed, matrixProps, selectedSeries } =
        useValues(logic)
    const { retry, setMode, setSelectedSeries, setWeeks } = useActions(logic)
    const [settingsOpen, setSettingsOpen] = useState(false)

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="account-dot-matrix-tile">
            <div className="flex flex-wrap items-center justify-end gap-2">
                <Popover
                    visible={settingsOpen}
                    onClickOutside={() => setSettingsOpen(false)}
                    overlay={
                        <div className="flex flex-col gap-3 p-3 w-64">
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
                            <LemonLabel htmlFor={`${generatedId}-weeks`}>Weeks</LemonLabel>
                            <LemonSelect<DotMatrixWeeks>
                                id={`${generatedId}-weeks`}
                                value={config.weeks}
                                onChange={setWeeks}
                                options={DOT_MATRIX_WEEK_OPTIONS.map((weeks) => ({
                                    value: weeks,
                                    label: `${weeks} weeks`,
                                }))}
                                fullWidth
                                aria-label="Dot matrix weeks"
                                data-attr="account-dot-matrix-weeks"
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
            {loadFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: retry, 'data-attr': 'account-dot-matrix-retry' }}
                >
                    Couldn't load activity for this account.
                </LemonBanner>
            ) : (
                <DotMatrix<AccountActivityMatrixDatum>
                    {...matrixProps}
                    mode={config.mode}
                    selectedSeries={selectedSeries}
                    onSelectedSeriesChange={setSelectedSeries}
                    loading={accountActivityMatrixLoading}
                    pageSize={MATRIX_PAGE_SIZE}
                    emptyState={emptyStateMessage(accountActivityMatrix, config.weeks)}
                />
            )}
            {accountActivityMatrix?.truncated ? (
                <span className="text-xs text-secondary">Showing the most active people.</span>
            ) : null}
        </div>
    )
}
