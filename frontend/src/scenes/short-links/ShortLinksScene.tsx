import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import { ProductKey, UserBasicType } from '~/types'

import { shortLinksLogic } from './shortLinksLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import stringWithWBR from 'lib/utils/stringWithWBR'

interface ShortLink {
    id: string
    destination: string
    created_at?: string
    created_by?: UserBasicType
    origin_domain?: string
    origin_key?: string
    custom_key?: string
    tags?: string[] | string
    description?: string
    comments?: string
    folder?: string
    expiration_date?: string
    password?: string
    og_title?: string
    og_description?: string
    og_image?: string | File
    utm_params?: Record<string, string>
    targeting?: Record<string, any>
}

export function ShortLinksScene(): JSX.Element {
    const { links, linksLoading } = useValues(shortLinksLogic)

    const columns = [
        {
            title: 'Key',
            dataIndex: 'key',
            sticky: true,
            width: '40%',
            render: function Render(_: any, record: ShortLink) {
                return (
                    <LemonTableLink
                        to={record.id ? urls.shortLink(record.id) : undefined}
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
        createdByColumn<ShortLink>() as LemonTableColumn<ShortLink, keyof ShortLink | undefined>,
        createdAtColumn<ShortLink>() as LemonTableColumn<ShortLink, keyof ShortLink | undefined>,
        {
            title: 'Last 7 days',
            render: function RenderSuccessRate(date: any, record: ShortLink) {
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
            render: function Render(date: any, record: ShortLink) {
                return (
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: `Edit link`,
                                        onClick: () => {},
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
                        onClick={() => router.actions.push(urls.shortLinkNew())}
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
                        Create short link
                    </LemonButton>
                }
            />

            {links.length === 0 && !linksLoading ? (
                <ProductIntroduction
                    productName="ShortLinks"
                    thingName="short link"
                    description="Start creating short links for your marketing campaigns, referral programs, and more."
                    action={() => router.actions.push(urls.shortLinkNew())}
                    isEmpty={links.length === 0}
                    productKey={ProductKey.SHORT_LINKS}
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
                    nouns={['short link', 'short links']}
                />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: ShortLinksScene,
    logic: shortLinksLogic,
}
