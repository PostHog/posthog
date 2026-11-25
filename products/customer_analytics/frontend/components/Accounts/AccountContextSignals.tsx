import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AccountContextSignal } from './accountContextData'
import { AccountContextDate } from './AccountContextDate'
import { accountContextLogic, type AccountContextLogicProps, type SignalState } from './accountContextLogic'
import { CONTEXT_WRITE_DISABLED_REASON } from './constants'

const SIGNAL_PAGE_SIZE = 5

function SignalContext({ signal }: { signal: AccountContextSignal }): JSX.Element {
    if (!signal.reason && !signal.notes.length) {
        return <span className="text-secondary">{signal.scheduled ? 'No note yet' : 'No reason or note yet'}</span>
    }
    return (
        <>
            {signal.reason ? (
                <span className="text-secondary">
                    <span className="font-medium">{signal.reason.likely ? 'Likely reason: ' : 'Reason: '}</span>
                    <span>{signal.reason.text}</span>
                </span>
            ) : null}
            {signal.notes.map((note) => (
                <span key={note} className="text-secondary">
                    <span className="font-medium">Note: </span>
                    <span>{note}</span>
                </span>
            ))}
        </>
    )
}

export function AccountContextSignals({
    logicProps,
    embedded,
}: {
    logicProps: AccountContextLogicProps
    embedded: boolean
}): JSX.Element {
    const logic = accountContextLogic(logicProps)
    const { visibleSignals, signalState, signalCounts } = useValues(logic)
    const { setSignalState } = useActions(logic)

    const columns: LemonTableColumns<AccountContextSignal> = [
        {
            title: 'Signal',
            key: 'title',
            render: (_, signal) => (
                <div className="flex flex-col gap-1 py-1">
                    <span className="font-medium">{signal.title}</span>
                    <SignalContext signal={signal} />
                </div>
            ),
        },
        {
            title: 'Since',
            key: 'onset',
            render: (_, signal) => (
                <span className="whitespace-nowrap">
                    <AccountContextDate date={signal.onset} />
                </span>
            ),
        },
        ...(signalState === 'closed'
            ? [
                  {
                      title: 'Closed',
                      key: 'closedOn',
                      render: (_: unknown, signal: AccountContextSignal) => (
                          <div className="flex flex-col whitespace-nowrap">
                              <AccountContextDate date={signal.closedOn} />
                              {signal.openDays !== null ? (
                                  <span className="text-xs text-secondary">
                                      Open {pluralize(signal.openDays, 'day')}
                                  </span>
                              ) : null}
                          </div>
                      ),
                  },
              ]
            : []),
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
                signal.open ? (
                    <div className="whitespace-nowrap">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                            data-attr="account-context-add-reason"
                        >
                            Add note
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
                        { value: 'open', label: `Open (${signalCounts.open})` },
                        { value: 'closed', label: `Recently closed (${signalCounts.closed})` },
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
