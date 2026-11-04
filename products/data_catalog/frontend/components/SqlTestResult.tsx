import clsx from 'clsx'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { SqlPreview } from '../dataCatalogNewMetricSceneLogic'
import { ResultCell } from './ResultCell'

const SINGLE_VALUE_MAX_FRACTION_DIGITS = 6

const PREVIEW_PAGE_SIZE = 5

export interface SqlTestResultProps {
    preview: SqlPreview
    unit: string
    stale: boolean
    loading: boolean
    onAddUnit: () => void
}

export function SqlTestResult({ preview, unit, stale, loading, onAddUnit }: SqlTestResultProps): JSX.Element {
    const isSingleValue = preview.rows.length === 1 && preview.columns.length === 1
    const singleValue = isSingleValue ? preview.rows[0][0] : undefined

    return (
        <div className={clsx('flex flex-col gap-2', (stale || loading) && 'opacity-60')} aria-live="polite">
            {preview.warnings.length > 0 && (
                <LemonBanner type="warning">
                    This result may be incomplete:
                    <ul className="list-disc pl-5">
                        {preview.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            {preview.rows.length === 0 ? (
                <p className="m-0 text-secondary">The query returned no rows.</p>
            ) : isSingleValue && typeof singleValue === 'number' ? (
                <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-2xl font-semibold tabular-nums" translate="no">
                        {humanFriendlyNumber(singleValue, SINGLE_VALUE_MAX_FRACTION_DIGITS)}
                    </span>
                    {unit.trim() ? (
                        <span className="text-secondary">{unit.trim()}</span>
                    ) : (
                        <Link onClick={onAddUnit} className="text-sm" data-attr="data-catalog-new-metric-add-unit">
                            Add a unit
                        </Link>
                    )}
                </div>
            ) : isSingleValue ? (
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className="text-secondary">{preview.columns[0]}</span>
                    <span className="font-semibold" translate="no">
                        {singleValue == null ? 'NULL' : <ResultCell value={singleValue} />}
                    </span>
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <LemonTable<unknown[]>
                        size="small"
                        dataSource={preview.rows}
                        pagination={{ pageSize: PREVIEW_PAGE_SIZE, useUrl: false }}
                        columns={preview.columns.map((column, index) => ({
                            title: column,
                            key: `${index}`,
                            render: (_, row) => <ResultCell value={row[index]} />,
                        }))}
                    />
                </div>
            )}
            <span className="text-xs text-secondary">
                {stale
                    ? 'The query changed since the last test.'
                    : preview.hasMore
                      ? `From your last test. Showing the first ${preview.rows.length} rows.`
                      : 'From your last test.'}
            </span>
        </div>
    )
}
