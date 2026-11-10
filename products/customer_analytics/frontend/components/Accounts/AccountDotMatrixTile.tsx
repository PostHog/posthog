import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { DotMatrix } from 'lib/components/DotMatrix/DotMatrix'

import type { ActivityMatrixDatum } from '../ProductActivity/activityMatrixTypes'
import { accountDotMatrixTileLogic } from './accountDotMatrixTileLogic'
import { AccountProductUsage } from './AccountProductUsage'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
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
        includeFirstUse,
    } = useValues(logic)
    const { retry, setSelectedSeries, chooseSource, setIncludeFirstUse } = useActions(logic)

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
                            {presentation.error && !queryEditorOpen && !matrixResultLoading ? (
                                <LemonBanner type="warning">{presentation.error}</LemonBanner>
                            ) : displayResult?.kind === 'product_usage' ? (
                                <AccountProductUsage
                                    result={displayResult.result}
                                    emptyState={presentation.empty}
                                    accountId={accountId}
                                    instanceId={`${instanceId ?? 'tile'}:${generatedId}:products`}
                                    includeFirstUse={includeFirstUse}
                                    onIncludeFirstUseChange={setIncludeFirstUse}
                                    loading={matrixResultLoading}
                                />
                            ) : (
                                (matrixResultLoading || (displayResult && !presentation.error)) && (
                                    <DotMatrix<ActivityMatrixDatum>
                                        {...presentation.matrix}
                                        embedded
                                        legend={
                                            presentation.matrix.legend === false
                                                ? false
                                                : { ...presentation.matrix.legend, hint: false }
                                        }
                                        mode={config.mode}
                                        countOf={
                                            presentation.matrix.countOf ??
                                            (sourceKind === 'hogql' ? 'value' : 'activeSeries')
                                        }
                                        selectedSeries={selectedSeries}
                                        onSelectedSeriesChange={
                                            sourceKind === 'hogql' && (presentation.matrix.series?.length ?? 0) <= 1
                                                ? undefined
                                                : setSelectedSeries
                                        }
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
