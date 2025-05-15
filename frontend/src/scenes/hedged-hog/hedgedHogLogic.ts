import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'

import type { hedgedHogLogicType } from './hedgedHogLogicType'

export interface HedgedHogData {
    name: string
    value: number
}

export interface Transaction {
    id: string
    user_email: string
    team_id: string
    entry_type: string
    transaction_type: string
    amount: number
    reference_id: string | null
    description: string
    created_at: string
}

export interface WalletBalanceResponse {
    balance: number
}

export interface OnboardingResponse {
    status: string
    message: string
    balance: number
}

export interface LeaderboardEntry {
    user_email: string
    balance?: number
    win_rate?: number
    total_bets?: number
    total_wins?: number
    total_volume?: number
}

export type LeaderboardType = 'balance' | 'win_rate' | 'volume'

export const hedgedHogLogic = kea<hedgedHogLogicType>([
    path(['scenes', 'hedged-hog', 'hedgedHogLogic']),

    actions({
        setData: (data: HedgedHogData) => ({ data }),
        loadTransactions: () => ({}),
        setActiveTab: (tab: string) => ({ tab }),
        loadLeaderboard: (leaderboardType: LeaderboardType = 'balance') => ({ leaderboardType }),
        setBetId: (betId: string | null) => ({ betId }),
        initializeWallet: true,
    }),

    reducers({
        hedgedHogData: [
            { name: 'Sample HedgedHog', value: 42 } as HedgedHogData,
            {
                setData: (_, { data }) => data,
            },
        ],
        transactions: [
            [] as Transaction[],
            {
                loadTransactionsSuccess: (_, { transactions }) => transactions,
            },
        ],
        walletBalance: [
            0,
            {
                loadWalletBalanceSuccess: (_, { walletBalance }) => walletBalance,
                initializeWalletSuccess: (_, { balance }) => balance.balance,
            },
        ],
        isOnboarded: [
            false,
            {
                loadTransactionsSuccess: (_, { transactions }) => transactions.length > 0,
                initializeWalletSuccess: () => true,
                initializeWalletFailure: (state, { error }) => {
                    // If the error is "User already onboarded", we consider the user as onboarded
                    // @ts-expect-error
                    if (error?.detail === 'User already onboarded') {
                        return true
                    }
                    return state
                },
            },
        ],
        activeTab: [
            '',
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        leaderboard: [
            [] as LeaderboardEntry[],
            {
                loadLeaderboardSuccess: (_, { leaderboard }) => leaderboard,
            },
        ],
        currentLeaderboardType: [
            'balance' as LeaderboardType,
            {
                loadLeaderboard: (_, { leaderboardType }) => leaderboardType,
            },
        ],
        leaderboardLoading: [
            false,
            {
                loadLeaderboard: () => true,
                loadLeaderboardSuccess: () => false,
                loadLeaderboardFailure: () => false,
            },
        ],
        betId: [
            null as string | null,
            {
                setBetId: (_, { betId }) => betId,
            },
        ],
    }),

    loaders(() => ({
        hedgedHogData: {
            loadHedgedHogData: async () => {
                // Replace with actual API call when ready
                await new Promise((resolve) => setTimeout(resolve, 500))
                return { name: 'Loaded HedgedHog', value: Math.floor(Math.random() * 100) }
            },
        },
        transactions: {
            loadTransactions: async () => {
                const response = await api.get(`api/projects/@current/transactions/`)
                return response.results as Transaction[]
            },
        },
        walletBalance: {
            loadWalletBalance: async () => {
                const response: WalletBalanceResponse = await api.get(
                    `api/projects/@current/transactions/wallet_balance/`
                )
                return response.balance
            },
        },
        balance: {
            initializeWallet: async () => {
                const response = await api.create(`api/projects/@current/onboarding/initialize/`)
                return response as OnboardingResponse
            },
        },
        leaderboard: {
            loadLeaderboard: async ({ leaderboardType }) => {
                const response = await api.get(
                    `api/projects/@current/transactions/leaderboard/?type=${leaderboardType}&limit=10`
                )
                return response as LeaderboardEntry[]
            },
        },
    })),

    selectors({
        dataMessage: [(s) => [s.hedgedHogData], (data: HedgedHogData) => `${data.name}: ${data.value}`],
        hasTransactions: [(s) => [s.transactions], (transactions) => transactions.length > 0],
    }),

    listeners(({ actions }) => ({
        loadTransactionsSuccess: ({ transactions }) => {
            // If we have transactions, also load the wallet balance
            if (transactions.length > 0) {
                actions.loadWalletBalance()
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            // Load transactions and wallet balance on mount
            actions.loadTransactions()
            actions.loadWalletBalance()
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/hedged-hog/bet/:betId': ({ betId }) => {
            if (betId !== values.betId) {
                actions.setBetId(betId ?? null)
            }
        },
    })),
])
