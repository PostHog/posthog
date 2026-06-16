'use client'

import { useCallback, useEffect, useState } from 'react'

import { useSetDockPage } from '@/components/dock-context'
import { LedgerFeed } from '@/components/LedgerFeed'
import { useSessionTeamId } from '@/components/session-context'
import { WalletCard } from '@/components/WalletCard'
import {
    ApiError,
    getWallet,
    listLedger,
    type AIGatewayLedgerEntry,
    type AIGatewayLedgerListResponse,
    type AIGatewayTransactionType,
    type AIGatewayWallet,
} from '@/lib/apiClient'

type FilterType = AIGatewayTransactionType | 'all'

const PAGE_SIZE = 50

export function BillingClient(): React.ReactElement {
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    useSetDockPage({ kind: 'agent-list' })

    return (
        <div className="mx-auto flex max-w-4xl flex-col gap-4 px-6 py-6">
            <header>
                <h1 className="text-lg font-medium text-foreground">Billing</h1>
                <p className="mt-1 text-xs text-muted-foreground">ai-gateway wallet and ledger for this team.</p>
            </header>
            <WalletSection teamId={teamId} />
            <LedgerSection teamId={teamId} />
        </div>
    )
}

function WalletSection({ teamId }: { teamId: number }): React.ReactElement {
    const [wallet, setWallet] = useState<AIGatewayWallet | null>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false
        setError(null)
        getWallet(teamId)
            .then((w) => {
                if (!cancelled) {
                    setWallet(w)
                }
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(formatError(err))
                }
            })
        return () => {
            cancelled = true
        }
    }, [teamId])

    if (error) {
        return (
            <div className="rounded-md border border-border bg-card px-3 py-3 text-xs text-destructive-foreground">
                Wallet unavailable: {error}
            </div>
        )
    }
    if (!wallet) {
        return (
            <div className="rounded-md border border-border bg-card px-3 py-3 text-xs italic text-muted-foreground">
                Loading wallet…
            </div>
        )
    }
    return <WalletCard wallet={wallet} />
}

function LedgerSection({ teamId }: { teamId: number }): React.ReactElement {
    const [filter, setFilter] = useState<FilterType>('all')
    const [page, setPage] = useState<AIGatewayLedgerListResponse>({ results: [], next_cursor: null })
    const [loading, setLoading] = useState(true)
    const [loadingMore, setLoadingMore] = useState(false)
    const [error, setError] = useState<string | undefined>(undefined)

    const fetchPage = useCallback(
        async (opts: { append: boolean; cursor?: string }): Promise<void> => {
            try {
                const res = await listLedger(teamId, {
                    limit: PAGE_SIZE,
                    cursor: opts.cursor,
                    transactionType: filter === 'all' ? undefined : filter,
                })
                setPage((prev) =>
                    opts.append
                        ? {
                              results: [...prev.results, ...res.results] as AIGatewayLedgerEntry[],
                              next_cursor: res.next_cursor ?? null,
                          }
                        : res
                )
                setError(undefined)
            } catch (err) {
                setError(formatError(err))
            }
        },
        [teamId, filter]
    )

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        fetchPage({ append: false }).finally(() => {
            if (!cancelled) {
                setLoading(false)
            }
        })
        return () => {
            cancelled = true
        }
    }, [fetchPage])

    const onLoadMore = useCallback(() => {
        const cursor = page.next_cursor ?? undefined
        if (!cursor) {
            return
        }
        setLoadingMore(true)
        fetchPage({ append: true, cursor }).finally(() => setLoadingMore(false))
    }, [fetchPage, page.next_cursor])

    return (
        <LedgerFeed
            page={page}
            loading={loading}
            error={error}
            filterType={filter}
            onChangeFilter={setFilter}
            onLoadMore={onLoadMore}
            loadingMore={loadingMore}
        />
    )
}

function formatError(err: unknown): string {
    if (err instanceof ApiError) {
        return err.message
    }
    if (err instanceof Error) {
        return err.message
    }
    return 'unknown error'
}
