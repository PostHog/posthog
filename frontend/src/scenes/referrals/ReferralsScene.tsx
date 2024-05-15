import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey, ReferralProgram } from '~/types'

import { referralsSceneLogic } from './referralsSceneLogic'

export const scene: SceneExport = {
    component: ReferralsScene,
    logic: referralsSceneLogic,
}

export function ReferralsScene(): JSX.Element {
    const { referrals, referralsLoading, showIntro } = useValues(referralsSceneLogic)
    const columns: LemonTableColumns<ReferralProgram> = [
        {
            title: 'Program',
            key: 'name',
            dataIndex: 'title',
            render(_, program) {
                return (
                    <LemonTableLink
                        title={program.title}
                        description={program.description}
                        to={urls.referralProgram(program.short_id)}
                    />
                )
            },
        },
        {
            title: 'Referrers',
            key: 'referrers',
            dataIndex: 'referrers_count',
        },
        {
            title: 'Redemptions',
            key: 'redemptions',
            dataIndex: 'redeemers_count',
        },
    ]

    return (
        <div>
            {showIntro && (
                <ProductIntroduction
                    productName="Referrals"
                    productKey={ProductKey.REFERRALS}
                    thingName="referral program"
                    description="Referrals allow you to track and reward users who refer others to your product."
                    docsURL="https://posthog.com/docs/referrals/manual"
                    action={() => router.actions.push(urls.createReferralProgram())}
                    isEmpty={true}
                />
            )}
            <LemonTable
                dataSource={referrals}
                columns={columns}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                noSortingCancellation
                loading={referralsLoading}
                pagination={{ pageSize: 100 }}
                nouns={['referral program', 'referral programs']}
                data-attr="feature-flag-table"
                emptyState="No referral programs created yet."
            />
        </div>
    )
}
