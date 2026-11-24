import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import type { AccountContextThread } from './accountContextData'
import { AccountContextDate } from './AccountContextDate'
import { accountContextLogic, type AccountContextLogicProps } from './accountContextLogic'

const THREAD_PAGE_SIZE = 5

export function AccountContextThreads({
    logicProps,
    embedded,
}: {
    logicProps: AccountContextLogicProps
    embedded: boolean
}): JSX.Element {
    const { context } = useValues(accountContextLogic(logicProps))

    const columns: LemonTableColumns<AccountContextThread> = [
        {
            title: 'Date',
            key: 'observedOn',
            render: (_, thread) => (
                <span className="whitespace-nowrap">
                    <AccountContextDate date={thread.observedOn} />
                </span>
            ),
        },
        {
            title: 'Summary',
            key: 'summary',
            render: (_, thread) => <span>{thread.summary}</span>,
        },
        {
            key: 'link',
            width: 0,
            render: (_, thread) =>
                thread.url ? (
                    <Link to={thread.url} target="_blank" className="whitespace-nowrap">
                        Open in Slack
                    </Link>
                ) : null,
        },
    ]

    return (
        <section className="flex flex-col gap-2">
            <h4 className="mb-0">From internal Slack</h4>
            <LemonTable<AccountContextThread>
                size="small"
                embedded={embedded}
                dataSource={context?.threads ?? []}
                columns={columns}
                rowKey="url"
                pagination={{ pageSize: THREAD_PAGE_SIZE, useUrl: false }}
                emptyState="No recent internal Slack threads."
            />
        </section>
    )
}
