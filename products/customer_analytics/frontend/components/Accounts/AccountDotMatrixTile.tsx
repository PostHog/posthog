import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'

import type { AccountActivityMatrixDatum } from './accountActivityMatrix'
import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { DotMatrixProductGroups } from './DotMatrixProductGroups'
import { DotMatrixQueryEditor } from './DotMatrixQueryEditor'
import { DotMatrixSourcePicker } from './DotMatrixSourcePicker'
import { DotMatrixTileSettings } from './DotMatrixTileSettings'

export interface AccountDotMatrixTileProps extends AccountViewTileLogicProps {
    accountId: string
    externalId?: string
}

export function AccountDotMatrixTile({
    accountId,
    externalId,
    instanceId,
    initialConfig,
    onConfigChange,
}: AccountDotMatrixTileProps): JSX.Element {
    const generatedId = useId()
    const logic = accountDotMatrixTileLogic({
        instanceId: `${instanceId ?? 'tile'}:${generatedId}`,
        accountId,
        externalId,
        initialConfig,
        onConfigChange,
    })
    const {
        displayResult,
        matrixResultLoading,
        config,
        loadError,
        presentation,
        selectedSeries,
        sourceKind,
        queryEditorOpen,
    } = useValues(logic)
    const { retry, setSelectedSeries, chooseSource } = useActions(logic)

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="account-dot-matrix-tile">
            {sourceKind === null ? (
                <>
                    <p className="text-secondary mb-0">Choose a data source to show activity in this tile.</p>
                    <DotMatrixSourcePicker id={`${generatedId}-source`} value={null} onChange={chooseSource} />
                </>
            ) : (
                <>
                    <DotMatrixTileSettings logic={logic} />
                    {queryEditorOpen && <DotMatrixQueryEditor logic={logic} />}
                    {loadError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: retry, 'data-attr': 'account-dot-matrix-retry' }}
                        >
                            {sourceKind === 'hogql' ? loadError : "Couldn't load activity for this account."}
                        </LemonBanner>
                    ) : (
                        <>
                            {displayResult?.kind === 'product_usage' && !matrixResultLoading && (
                                <DotMatrixProductGroups
                                    groupings={displayResult.result.groupings}
                                    onSelect={setSelectedSeries}
                                />
                            )}
                            {presentation.error && !queryEditorOpen && !matrixResultLoading ? (
                                <LemonBanner type="warning">{presentation.error}</LemonBanner>
                            ) : (
                                (matrixResultLoading || (displayResult && !presentation.error)) && (
                                    <DotMatrix<AccountActivityMatrixDatum>
                                        {...presentation.matrix}
                                        mode={config.mode}
                                        countOf={sourceKind === 'hogql' ? 'value' : 'activeSeries'}
                                        selectedSeries={selectedSeries}
                                        onSelectedSeriesChange={setSelectedSeries}
                                        loading={matrixResultLoading}
                                        pageSize={20}
                                        emptyState={presentation.empty}
                                    />
                                )
                            )}
                            {!matrixResultLoading &&
                                presentation.notices.map((notice) => (
                                    <span
                                        key={notice}
                                        className="text-xs text-secondary"
                                        data-attr="account-dot-matrix-notice"
                                    >
                                        {notice}
                                    </span>
                                ))}
                        </>
                    )}
                </>
            )}
        </div>
    )
}
