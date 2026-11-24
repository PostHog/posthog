import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { AccountContextSignal } from './accountContextData'
import { AccountContextDate } from './AccountContextDate'
import { accountContextLogic, type AccountContextLogicProps, type SignalState } from './accountContextLogic'
import { CONTEXT_WRITE_DISABLED_REASON } from './constants'

const SIGNAL_PAGE_SIZE = 5

export function AccountContextSignals({
    logicProps,
    embedded,
}: {
    logicProps: AccountContextLogicProps
    embedded: boolean
}): JSX.Element {
    const logic = accountContextLogic(logicProps)
    const { visibleSignals, signalState } = useValues(logic)
    const { setSignalState } = useActions(logic)

    const columns: LemonTableColumns<AccountContextSignal> = [
        {
            title: 'Signal',
            key: 'title',
            render: (_, signal) => (
                <div className="flex flex-col gap-1 py-1">
                    <span className="font-medium">{signal.title}</span>
                    {signal.reason ? (
                        <span className="text-secondary">
                            <span className="font-medium">{signal.reason.likely ? 'Likely reason: ' : 'Reason: '}</span>
                            <span>{signal.reason.text}</span>
                        </span>
                    ) : (
                        <span className="text-secondary">No known reason yet</span>
                    )}
                </div>
            ),
        },
        {
            title: signalState === 'open' ? 'Since' : 'Closed',
            key: 'date',
            render: (_, signal) => (
                <span className="whitespace-nowrap">
                    <AccountContextDate date={signalState === 'open' ? signal.onset : signal.closedOn} />
                </span>
            ),
        },
        {
            title: 'At stake',
            key: 'arrAtStake',
            render: (_, signal) => (
                <span className="whitespace-nowrap">
                    {signal.arrAtStake ? `${humanFriendlyCurrency(signal.arrAtStake, 0)} ARR` : 'Not measured'}
                </span>
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, signal) =>
                signal.open && !signal.reason ? (
                    <div className="whitespace-nowrap">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                            data-attr="account-context-add-reason"
                        >
                            Add reason
                        </LemonButton>
                    </div>
                ) : null,
        },
    ]

    return (
        <section className="flex flex-col gap-2">
            <h4 className="mb-0">Signals</h4>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton<SignalState>
                    size="small"
                    value={signalState}
                    onChange={setSignalState}
                    options={[
                        { value: 'open', label: 'Open' },
                        { value: 'closed', label: 'Recently closed' },
                    ]}
                />
            </div>
            <LemonTable<AccountContextSignal>
                size="small"
                embedded={embedded}
                dataSource={visibleSignals}
                columns={columns}
                rowKey="id"
                key={signalState}
                pagination={{ pageSize: SIGNAL_PAGE_SIZE, useUrl: false }}
                emptyState={signalState === 'open' ? 'No open signals.' : 'No signals closed in the last 90 days.'}
            />
        </section>
    )
}
