import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'

import { BIDrilldownProps, biDrilldownLogic } from './biDrilldownLogic'

export function BIDrilldownModal({ logicProps: props }: { logicProps: BIDrilldownProps }): JSX.Element {
    const { selection, queries, showRows } = useValues(biDrilldownLogic(props))
    const { close, viewRows } = useActions(biDrilldownLogic(props))
    return (
        <LemonModal title="Explore this result" isOpen={!!selection} onClose={close} width={showRows ? '90vw' : 520}>
            {queries ? (
                <div className="flex flex-col gap-3">
                    <p className="m-0">
                        {selection?.previous ? 'Comparison period' : 'Current period'} ·{' '}
                        {selection?.filters.length ? 'Selected dimensions' : 'All matching rows'}
                    </p>
                    {selection?.labels.length ? (
                        <ul className="m-0 pl-4">
                            {selection.labels.map((label, index) => (
                                <li key={index} className="break-words">
                                    {label.name}: {label.value}
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            onClick={close}
                            to={
                                queries.worksheet
                                    ? `${urls.businessIntelligence()}#q=${encodeURIComponent(JSON.stringify(queries.worksheet))}`
                                    : undefined
                            }
                            disabledReason={
                                !queries.worksheet
                                    ? 'Open comparison-period rows below to explore their original dates'
                                    : undefined
                            }
                        >
                            Filter in new worksheet
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={viewRows}
                            disabledReason={showRows ? 'Underlying rows are already open' : undefined}
                        >
                            View underlying rows
                        </LemonButton>
                        <LemonButton type="secondary" to={urls.sqlEditor({ query: queries.rows })} onClick={close}>
                            Open in SQL editor
                        </LemonButton>
                    </div>
                    {showRows ? (
                        <>
                            <p className="m-0 text-secondary">
                                Showing up to 1,000 source rows, before aggregation or table calculations.
                            </p>
                            <Query query={queries.rows} uniqueKey={`${props.key}.underlying`} readOnly embedded />
                        </>
                    ) : null}
                </div>
            ) : null}
        </LemonModal>
    )
}
