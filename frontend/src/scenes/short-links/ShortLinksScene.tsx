import { IconCopy, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { shortLinksLogic } from './shortLinksLogic'

interface ShortLink {
    id: string
    destination: string
    created_at?: string
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

    const baseUrl = `${window.location.origin}/e`

    const columns = [
        {
            title: 'Short URL',
            dataIndex: 'id' as keyof ShortLink,
            render: function RenderKey(id: any, record: ShortLink) {
                if (!id) {
                    return null
                }
                const shortUrl = `${baseUrl}/${id}`
                return (
                    <div className="flex items-center gap-2">
                        <Link to={shortUrl} target="_blank">
                            {shortUrl}
                        </Link>
                        <LemonButton
                            icon={<IconCopy />}
                            size="small"
                            onClick={() => {
                                void navigator.clipboard.writeText(shortUrl)
                            }}
                            tooltip="Copy to clipboard"
                        />
                    </div>
                )
            },
        },
        {
            title: 'Destination',
            dataIndex: 'destination' as keyof ShortLink,
            render: function RenderDestination(destination: any, record: ShortLink) {
                if (!destination) {
                    return null
                }
                return (
                    <div className="max-w-100 overflow-hidden">
                        <Link to={destination} target="_blank" className="truncate">
                            {destination}
                        </Link>
                    </div>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at' as keyof ShortLink,
            render: function RenderDate(date: any, record: ShortLink) {
                if (!date) {
                    return null
                }
                return <span className="text-sm">{dayjs(date).format('MMM D, YYYY')}</span>
            },
        },
        {
            title: 'Origin',
            dataIndex: 'origin_domain' as keyof ShortLink,
            render: function RenderOrigin(domain: any, record: ShortLink) {
                if (!domain) {
                    return <span className="text-muted text-sm">None</span>
                }
                return <span className="text-sm">{domain}</span>
            },
        },
        {
            title: 'Actions',
            dataIndex: 'id' as keyof ShortLink,
            width: 100,
            render: function RenderActions(id: any, record: ShortLink) {
                if (!id) {
                    return null
                }
                return (
                    <div className="flex gap-2 justify-end">
                        <LemonButton
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => {}}
                            tooltip="Edit"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            status="danger"
                            size="small"
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete short link?',
                                    description: (
                                        <>
                                            Are you sure you want to delete the short link{' '}
                                            <code>
                                                {baseUrl}/{id}
                                            </code>
                                            ?
                                        </>
                                    ),
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Delete',
                                        onClick: () => {},
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            }}
                            tooltip="Delete"
                        />
                    </div>
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
