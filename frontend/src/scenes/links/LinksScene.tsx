import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { LinkType } from './linkConfigurationLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { linksLogic } from './linksLogic'

export function LinksScene(): JSX.Element {
    const { links, linksLoading } = useValues(linksLogic())

    const columns = [
        {
            title: 'Key',
            dataIndex: 'key',
            sticky: true,
            width: '40%',
            render: function Render(_: any, record: LinkType) {
                return (
                    <LemonTableLink
                        to={record.id ? urls.link(record.id) : undefined}
                        title={
                            <>
                                <span>{stringWithWBR(record?.origin_domain + '/' + record?.origin_key || '', 17)}</span>
                            </>
                        }
                        description={record?.destination}
                    />
                )
            },
        },
        createdByColumn<LinkType>() as LemonTableColumn<LinkType, keyof LinkType | undefined>,
        createdAtColumn<LinkType>() as LemonTableColumn<LinkType, keyof LinkType | undefined>,
        {
            title: 'Last 7 days',
            render: function RenderSuccessRate(date: any, record: LinkType) {
                return (
                    <span>sparkline for clicks in the last 7 days</span>
                    // <Link
                    //     to={urls.pipelineNode(
                    //         hogFunctionTypeToPipelineStage(destination.stage),
                    //         destination.id,
                    //         PipelineNodeTab.Metrics
                    //     )}
                    // >
                    //     {destination.backend === PipelineBackend.HogFunction ? (
                    //         <HogFunctionMetricSparkLine id={destination.hog_function.id} />
                    //     ) : (
                    //         <AppMetricSparkLine pipelineNode={destination} />
                    //     )}
                    // </Link>
                )
            },
        },
        {
            width: 0,
            render: function Render(_: any, record: LinkType) {
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: `Edit link`,
                                        onClick: () => router.actions.push(urls.link(record.id)),
                                    },
                                    {
                                        label: `Delete link`,
                                        status: 'danger' as const,
                                        onClick: () => {},
                                    },
                                ]}
                            />
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => router.actions.push(urls.link('new'))}
                        sideAction={{
                            dropdown: {
                                overlay: (
                                    <>
                                        <LemonButton fullWidth onClick={() => {}}>
                                            Import from Bit.ly
                                        </LemonButton>
                                        <LemonButton fullWidth onClick={() => {}}>
                                            Import from Dub.co
                                        </LemonButton>
                                        <LemonButton fullWidth onClick={() => {}}>
                                            Import from CSV
                                        </LemonButton>
                                    </>
                                ),
                                placement: 'bottom-end',
                            },
                        }}
                    >
                        Create link
                    </LemonButton>
                }
            />

            {links.length === 0 && !linksLoading ? (
                <ProductIntroduction
                    productName="Links"
                    thingName="link"
                    description="Start creating links for your marketing campaigns, referral programs, and more."
                    action={() => router.actions.push(urls.link('new'))}
                    isEmpty={links.length === 0}
                    productKey={ProductKey.LINKS}
                />
            ) : (
                <LemonTable
                    dataSource={links}
                    columns={columns}
                    loading={linksLoading}
                    rowKey="id"
                    pagination={{ pageSize: 100 }}
                    defaultSorting={{
                        columnKey: 'created_at',
                        order: -1,
                    }}
                    nouns={['link', 'links']}
                />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: LinksScene,
    logic: linksLogic,
}
