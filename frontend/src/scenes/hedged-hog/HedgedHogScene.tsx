import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/types'

import { BetDefinitionsContent } from './HedgedHogBetDefinitions'
import { HomeContent } from './HedgedHogHome'
import { LeaderboardContent } from './HedgedHogLeaderboard'
import { hedgedHogLogic } from './hedgedHogLogic'
import { WalletContent } from './HedgedHogWallet'

export const scene: SceneExport = {
    component: HedgedHogScene,
    logic: hedgedHogLogic,
}

type Tab = 'home' | 'wallet' | 'bet-definitions' | 'leaderboard'

export function HedgedHogScene(): JSX.Element {
    const { location, searchParams } = useValues(router)
    const { replace } = useActions(router)

    const { isOnboarded, transactionsLoading, walletBalanceLoading } = useValues(hedgedHogLogic)
    const { loadTransactions, loadWalletBalance, initializeWallet } = useActions(hedgedHogLogic)

    // Get the active tab from URL query parameters or default to 'home'
    const tabFromUrl = searchParams.tab as Tab
    const activeTab: Tab = ['home', 'wallet', 'bet-definitions', 'leaderboard'].includes(tabFromUrl)
        ? tabFromUrl
        : 'home'

    // Update the URL when tab changes
    const setActiveTab = (tab: Tab): void => {
        // Create a new URLSearchParams object
        const newParams = new URLSearchParams(searchParams as Record<string, string>)
        newParams.set('tab', tab)

        // Use replace with the current pathname and the new search string
        replace(`${location.pathname}?${newParams.toString()}`)
    }

    return (
        <div className="px-4">
            <h1 className="mb-2">HedgedHog Betting</h1>
            <PageHeader
                caption="Place bets on key metrics and win rewards"
                buttons={
                    isOnboarded ? (
                        <LemonButton
                            type="primary"
                            icon={<IconRefresh />}
                            onClick={() => {
                                loadTransactions()
                                loadWalletBalance()
                            }}
                            loading={transactionsLoading || walletBalanceLoading}
                        >
                            Refresh
                        </LemonButton>
                    ) : undefined
                }
            />

            {!isOnboarded ? (
                <ProductIntroduction
                    productName="Hedged Hog"
                    productKey={ProductKey.HEDGED_HOG}
                    thingName="hedged hog"
                    description="Welcome to the bright new future of betting on your own growth"
                    isEmpty={true}
                    action={() => initializeWallet()}
                />
            ) : (
                <div className="max-w-5xl mx-auto">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as Tab)}
                        tabs={[
                            {
                                key: 'home',
                                label: 'Home',
                                // icon: <IconHome />,
                                content: <HomeContent />,
                            },
                            {
                                key: 'wallet',
                                label: 'Wallet',
                                // icon: <IconWallet />,
                                content: <WalletContent />,
                            },
                            {
                                key: 'bet-definitions',
                                label: 'Bet Definitions',
                                // icon: <IconTarget />,
                                content: <BetDefinitionsContent />,
                            },
                            {
                                key: 'leaderboard',
                                label: 'Leaderboard',
                                // icon: <IconTrophy />,
                                content: <LeaderboardContent />,
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
