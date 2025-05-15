import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import { router } from 'kea-router'
import api from 'lib/api'
import { urls } from 'scenes/urls'

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

export interface Bet {
    id: string
    bet_definition: string
    bet_definition_title: string
    amount: number
    predicted_value: number
    potential_payout: number
    created_at: string
    user: {
        id: string
        email: string
    }
}

export const hedgedHogLogic = kea<hedgedHogLogicType>([
    path(['scenes', 'hedged-hog', 'hedgedHogLogic']),

    actions({
        setData: (data: HedgedHogData) => ({ data }),
        loadTransactions: () => ({}),
        setActiveTab: (tab: string) => ({ tab }),
        loadLeaderboard: (leaderboardType: LeaderboardType = 'balance') => ({ leaderboardType }),
        setBetId: (betId: string | null) => ({ betId }),
        initializeWallet: true,
        goBackToBets: true,
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
                    if (error?.detail === 'User already onboarded') {
                        return true
                    }
                    return state
                },
            },
        ],
        activeTab: [
            'betting',
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
                const response = await api.get('api/projects/@current/hedged-hog/')
                return response
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
        allBets: [
            [] as Bet[],
            {
                loadAllBets: async (betDefinitionId: string) => {
                    const response = await api.get(
                        `api/projects/@current/bets/by_definition/?bet_definition_id=${betDefinitionId}`
                    )
                    return response
                },
            },
        ],
        userBets: [
            [] as Bet[],
            {
                loadUserBets: async (betDefinitionId: string) => {
                    const response = await api.get(
                        `api/projects/@current/bets/my_bets/?bet_definition_id=${betDefinitionId}`
                    )
                    return response
                },
            },
        ],
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
        currentBet: [
            (s) => [s.allBets, s.betId],
            (allBets: Bet[], betId: string | null) => allBets.find((bet) => bet.id === betId),
        ],
    }),

    listeners(({ actions }) => ({
        loadTransactionsSuccess: ({ transactions }) => {
            // If we have transactions, also load the wallet balance
            if (transactions.length > 0) {
                actions.loadWalletBalance()
            }
        },
        initializeWallet: async () => {
            actions.loadTransactions()
            actions.loadWalletBalance()
        },
        setActiveTab: ({ tab }) => {
            const { push } = router.actions
            if (tab === 'betting') {
                push(urls.hedgedHog())
            } else if (tab === 'wallet') {
                push(urls.hedgedHogWallet())
            } else if (tab === 'my-bets') {
                push(urls.hedgedHogMyBets())
            }
        },
        goBackToBets: () => {
            actions.setBetId(null)
            router.actions.push(urls.hedgedHog())
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            // Load transactions and wallet balance on mount
            actions.loadTransactions()
            actions.loadWalletBalance()
            const { betId } = router.values.hashParams
            if (betId) {
                actions.setBetId(betId)
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/hedged-hog': (_, searchParams) => {
            if (searchParams.tab) {
                actions.setActiveTab(searchParams.tab)
            }
        },
        '/hedged-hog/bet/:betId': ({ betId }) => {
            if (betId !== values.betId) {
                actions.setBetId(betId)
            }
        },
    })),
])
