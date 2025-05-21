import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { CountedPaginatedResponse } from 'lib/api'
import { walletLogicType } from './walletLogicType'

export interface Transaction {
    id: string
    entry_type: string
    transaction_type: string
    source: string
    destination: string
    amount: number
    reference_id: string | null
    description: string
    created_at: string
}

export interface WalletBalanceResponse {
    balance: number
    initialized: boolean
}

export const walletLogic = kea<walletLogicType>([
    path(['scenes', 'wallet', 'walletLogic']),

    actions({
        loadTransactions: () => ({}),
        initializeWallet: true,
    }),

    loaders(() => ({
        transactions: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<Transaction>,
            loadTransactions: async () => {
                const response: CountedPaginatedResponse<Transaction> = await api.get('api/wallet/transactions/')
                return response
            },
        },
        walletState: {
            __default: { balance: 0, initialized: false } as WalletBalanceResponse,
            loadWalletBalance: async () => {
                const response: WalletBalanceResponse = await api.get('api/wallet/balance/')
                return response
            },
            initializeWallet: async () => {
                const response: WalletBalanceResponse = await api.create('api/wallet/initialize/')
                return response
            },
        },
    })),

    selectors({
        balance: [(s) => [s.walletState], (state) => state.balance],
        isInitialized: [(s) => [s.walletState], (state) => state.initialized],
        hasTransactions: [(s) => [s.transactions], (transactions) => transactions.results.length > 0],
    }),

    listeners(({ actions }) => ({
        initializeWallet: async (_, breakpoint) => {
            await breakpoint(200)
            actions.loadTransactions()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadTransactions()
            actions.loadWalletBalance()
        },
    })),
])