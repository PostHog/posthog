import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/types'

import { BetDetailContent } from './HedgedHogBetDetail'
import { BettingContent } from './HedgedHogBetting'
import { LeaderboardContent } from './HedgedHogLeaderboard'
import { hedgedHogLogic } from './hedgedHogLogic'
import { MyBetsContent } from './HedgedHogMyBets'
import { WalletContent } from './HedgedHogWallet'

export const scene: SceneExport = {
    component: HedgedHogScene,
    logic: hedgedHogLogic,
}

type Tab = 'betting' | 'wallet' | 'leaderboard' | 'my-bets'

export function HedgedHogScene(): JSX.Element {
    const { location, searchParams } = useValues(router)
    const { replace } = useActions(router)
    const { betId, isOnboarded } = useValues(hedgedHogLogic)
    const { initializeWallet } = useActions(hedgedHogLogic)

    // Get the active tab from URL query parameters or default to 'betting'
    const tabFromUrl = searchParams.tab as Tab
    const activeTab: Tab = ['betting', 'wallet', 'leaderboard', 'my-bets'].includes(tabFromUrl) ? tabFromUrl : 'betting'

    // Update the URL when tab changes
    const setActiveTab = (tab: Tab): void => {
        // Create a new URLSearchParams object
        const newParams = new URLSearchParams(searchParams as Record<string, string>)
        newParams.set('tab', tab)

        // Use replace with the current pathname and the new search string
        replace(`${location.pathname}?${newParams.toString()}`)
    }

    if (betId) {
        return <BetDetailContent />
    }

    return (
        <div className="px-4">
            <h1 className="mb-2">Hedged Hog</h1>
            <PageHeader caption="Place bets on key metrics and win rewards" />

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
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as Tab)}
                    tabs={[
                        {
                            key: 'betting',
                            label: 'Betting',
                            content: <BettingContent />,
                        },
                        {
                            key: 'my-bets',
                            label: 'My Bets',
                            content: <MyBetsContent />,
                        },
                        {
                            key: 'wallet',
                            label: 'Wallet',
                            content: <WalletContent />,
                        },
                        {
                            key: 'leaderboard',
                            label: 'Leaderboard',
                            content: <LeaderboardContent />,
                        },
                    ]}
                />
            )}
        </div>
    )
}
