import { IconCopy, IconPencil, IconPlus, IconTrash, IconRefresh, IconPin as IconLink, IconCode as IconQrCode, IconDownload, IconGear as IconSettings, IconCalendar, IconLock, IconSort as IconExport, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, Link, LemonSelect, LemonTag, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { useState } from 'react'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { QRCodeSVG } from 'qrcode.react'

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
    const { shortLinks, shortLinksLoading, link } = useValues(shortLinksLogic)
    const { loadShortLinks, submitLink, setLinkValue, resetLink } = useActions(shortLinksLogic)
    
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
    const [editingLinkId, setEditingLinkId] = useState<string | null>(null)

    const baseUrl = `${window.location.origin}/e`
    
    // Filter active and expired links
    const activeShortLinks = shortLinks?.filter((link: ShortLink) => !link.expiration_date || new Date(link.expiration_date) > new Date()) || []
    const expiredShortLinks = shortLinks?.filter((link: ShortLink) => link.expiration_date && new Date(link.expiration_date) <= new Date()) || []

    const openCreateModal = (): void => {
        resetLink()
        setIsCreateModalOpen(true)
    }

    const closeCreateModal = (): void => {
        setIsCreateModalOpen(false)
    }

    const openEditModal = (shortLink: ShortLink): void => {
        resetLink(shortLink)
        setEditingLinkId(shortLink.id)
    }

    const closeEditModal = (): void => {
        setEditingLinkId(null)
    }

    const deleteShortLink = async (id: string): Promise<void> => {
        // Implementation would go here
        // After deletion, reload the links
        await loadShortLinks()
    }

    const columns = [
        {
            title: 'Short URL',
            dataIndex: 'id',
            render: function RenderKey(id: string) {
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
            render: function RenderDestination(destination: string) {
                if (!destination) {
                    return null
                }
                return (
                    <Link to={destination} target="_blank" className="truncate max-w-100">
                        {destination}
                    </Link>
                )
            },
        },
        {
            title: 'Created',
            dataIndex: 'created_at' as keyof ShortLink,
            render: function RenderDate(date: string) {
                if (!date) {
                    return null
                }
                return dayjs(date).format('MMM D, YYYY')
            },
        },
        {
            title: 'Origin',
            dataIndex: 'origin_domain' as keyof ShortLink,
            render: function RenderOrigin(domain: string) {
                if (!domain) {
                    return <span className="text-muted">None</span>
                }
                return domain
            },
        },
        {
            title: 'Actions',
            dataIndex: 'id' as keyof ShortLink,
            render: function RenderActions(id: string, record: ShortLink) {
                if (!id) {
                    return null
                }
                return (
                    <div className="flex gap-2">
                        <LemonButton
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => openEditModal(record)}
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
                                        onClick: () => deleteShortLink(id),
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

            {activeShortLinks.length === 0 && !shortLinksLoading ? (
                <ProductIntroduction
                    productName="ShortLinks"
                    thingName="short link"
                    description="Start creating short links for your marketing campaigns, referral programs, and more."
                    action={() => router.actions.push(urls.shortLinkNew())}
                    isEmpty={activeShortLinks.length === 0}
                    productKey={ProductKey.SHORT_LINKS}
                />
            ) : (
                <LemonTable
                    dataSource={activeShortLinks}
                    columns={columns}
                    loading={shortLinksLoading}
                    rowKey="id"
                    pagination={{ pageSize: 10 }}
                    defaultSorting={{
                        columnKey: 'created_at',
                        order: -1,
                    }}
                    nouns={['short link', 'short links']}
                />
            )}

            {expiredShortLinks.length > 0 && (
                <>
                    <div className="mt-8 mb-4">
                        <h2>Expired Links</h2>
                        <p className="text-muted mb-0">These links have expired and are no longer active</p>
                    </div>
                    <LemonTable
                        dataSource={expiredShortLinks}
                        columns={columns}
                        rowKey="id"
                        pagination={{ pageSize: 10 }}
                        nouns={['expired link', 'expired links']}
                    />
                </>
            )}

            {/* Create short link modal */}
            <LemonModal
                isOpen={isCreateModalOpen}
                onClose={closeCreateModal}
                width={900}
                closable={true}
                footer={
                    <div className="flex justify-between w-full">
                        <div>
                            <LemonButton
                                icon={<IconExport />}
                                onClick={() => {}} 
                                type="secondary"
                            >
                                UTM
                            </LemonButton>
                            <LemonButton
                                icon={<IconSettings />}
                                onClick={() => {}} 
                                type="secondary"
                                className="ml-2"
                            >
                                Targeting
                            </LemonButton>
                            <LemonButton
                                icon={<IconLock />}
                                onClick={() => {}} 
                                type="secondary"
                                className="ml-2"
                            >
                                Password
                            </LemonButton>
                            <LemonButton
                                icon={<IconCalendar />}
                                onClick={() => {}} 
                                type="secondary"
                                className="ml-2"
                            >
                                Expiration
                            </LemonButton>
                        </div>
                        <div>
                            <LemonButton
                                onClick={() => {
                                    submitLink()
                                    closeCreateModal()
                                }}
                                type="primary"
                                disabled={!link.destination}
                            >
                                Create link
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <Form
                    id="link"
                    formKey="link"
                    logic={shortLinksLogic}
                    className="space-y-4"
                    enableFormOnSubmit
                >
                    <div className="flex gap-8">
                        {/* Left side */}
                        <div className="flex-1 space-y-6">
                            <LemonField name="destination" label="Destination URL">
                                <LemonInput
                                    placeholder="https://example.com"
                                    fullWidth
                                    autoWidth={false}
                                />
                            </LemonField>
                            
                            <div className="flex flex-col gap-2">
                                <LemonLabel>Short Link</LemonLabel>
                                <div className="flex gap-2">
                                    <LemonField name="origin_domain">
                                        <LemonSelect
                                            options={[
                                                { label: 'postho.gg', value: 'postho.gg/' },
                                                { label: 'phog.gg', value: 'phog.gg/' },
                                                { label: 'hog.gg', value: 'hog.gg/' }
                                            ]}
                                            className="text-muted"
                                        />
                                    </LemonField>
                                    <LemonField name="origin_key" className="w-full">
                                        <LemonInput
                                            fullWidth
                                            placeholder="(optional)"
                                            className="flex-1"
                                            autoWidth={false}
                                        />
                                    </LemonField>
                                </div>
                            </div>
                            
                            <LemonField name="tags" label="Tags">
                                <LemonInputSelect
                                    placeholder="Select tags..."
                                    mode="multiple"
                                    allowCustomValues
                                    fullWidth
                                    autoWidth={false}
                                />
                            </LemonField>

                            <LemonField name="comments" label="Comments">
                                <LemonTextArea
                                    placeholder="Add comments"
                                    minRows={2}
                                />
                            </LemonField>
                        </div>

                        <LemonDivider vertical />
                        
                        <div className="flex-1 space-y-6 max-w-80">
                            <div>
                                <div className="flex justify-between items-center">
                                    <LemonLabel>
                                        <span className="flex items-center gap-1">
                                            QR Code
                                        </span>
                                    </LemonLabel>
                                    <div className="flex flex-row">
                                        <LemonButton
                                            icon={<IconDownload />}
                                            size="xsmall"
                                            onClick={() => {}}
                                            tooltip="Download QR code"
                                        />
                                        <LemonButton
                                            icon={<IconCopy />}
                                            size="xsmall"
                                            onClick={() => {}}
                                            tooltip="Copy to clipboard"
                                        />
                                    </div>
                                </div>
                                
                                <div className="border rounded-md p-4 mt-2 bg-bg-light flex items-center justify-center">
                                    <div className="text-center">
                                        <QRCodeSVG 
                                            size={128} 
                                            value={link.destination || "https://posthog.com"}
                                            imageSettings={{
                                                src: '/static/posthog-icon.svg',
                                                height: 40,
                                                width: 40,
                                                excavate: true
                                            }}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </Form>
            </LemonModal>

            {/* Edit short link modal */}
            <LemonModal
                isOpen={!!editingLinkId}
                title={
                    <div className="flex items-center gap-2">
                        <span>Links</span>
                        <span className="text-muted">›</span>
                        <div className="flex items-center gap-1">
                            <LemonTag type="primary">E</LemonTag>
                            <span>Edit link</span>
                        </div>
                    </div>
                }
                onClose={closeEditModal}
                width={900}
                closable={true}
                footer={
                    <div className="flex justify-end">
                        <LemonButton
                            onClick={closeEditModal} 
                            type="secondary"
                            className="mr-2"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                submitLink()
                                closeEditModal()
                            }}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <Form
                    id="link"
                    formKey="link"
                    logic={shortLinksLogic}
                    className="space-y-4"
                    enableFormOnSubmit
                >
                    <div className="flex gap-8">
                        {/* Left side */}
                        <div className="flex-1 space-y-6">
                            <div>
                                <LemonLabel>Short URL</LemonLabel>
                                <div className="flex items-center border rounded px-2 py-1 bg-bg-light font-mono">
                                    {baseUrl}/{link.id}
                                    <LemonButton
                                        icon={<IconCopy />}
                                        size="small"
                                        className="ml-2"
                                        onClick={() => {
                                            void navigator.clipboard.writeText(`${baseUrl}/${link.id}`)
                                        }}
                                    />
                                </div>
                            </div>
                            
                            <LemonField name="destination" label="Destination URL">
                                <LemonInput
                                    placeholder="https://example.com"
                                    fullWidth
                                    autoWidth={false}
                                />
                            </LemonField>
                            
                            <div className="flex flex-col gap-2">
                                <LemonLabel>Short Link</LemonLabel>
                                <div className="flex gap-2">
                                    <LemonField name="origin_domain">
                                        <LemonSelect
                                            options={[
                                                { label: 'postho.gg', value: 'postho.gg/' },
                                                { label: 'phog.gg', value: 'phog.gg/' },
                                                { label: 'hog.gg', value: 'hog.gg/' }
                                            ]}
                                            className="text-muted"
                                        />
                                    </LemonField>
                                    <LemonField name="origin_key" className="w-full">
                                        <LemonInput
                                            fullWidth
                                            placeholder="(optional)"
                                            className="flex-1"
                                            autoWidth={false}
                                        />
                                    </LemonField>
                                </div>
                            </div>
                            
                            <LemonField name="tags" label="Tags">
                                <LemonInputSelect
                                    placeholder="Select tags..."
                                    mode="multiple"
                                    allowCustomValues
                                    fullWidth
                                    autoWidth={false}
                                />
                            </LemonField>

                            <LemonField name="comments" label="Comments">
                                <LemonTextArea
                                    placeholder="Add comments"
                                    minRows={2}
                                />
                            </LemonField>
                            
                            <LemonField name="folder" label="Folder">
                                <LemonSelect
                                    options={[
                                        { value: 'Links', label: 'Links' },
                                        { value: 'Marketing', label: 'Marketing' },
                                        { value: 'Social', label: 'Social' },
                                    ]}
                                    fullWidth
                                />
                            </LemonField>
                            
                            <LemonField name="expiration_date" label="Expiration Date (optional)">
                                <LemonInput
                                    type="text"
                                    placeholder="YYYY-MM-DD"
                                    fullWidth
                                    autoWidth={false}
                                />
                                <div className="text-muted text-xs mt-1">
                                    The link will stop working after this date
                                </div>
                            </LemonField>
                        </div>
                        
                        {/* Right side */}
                        <div className="flex-1 space-y-6">
                            <div>
                                <div className="flex justify-between items-center">
                                    <LemonLabel>
                                        <span className="flex items-center gap-1">
                                            QR Code
                                            <LemonButton status="alt" size="small" icon={<IconQrCode />} />
                                        </span>
                                    </LemonLabel>
                                    <LemonButton
                                        icon={<IconDownload />}
                                        type="secondary"
                                        size="small"
                                    >
                                        Download
                                    </LemonButton>
                                </div>
                                
                                <div className="border rounded-md p-4 mt-2 bg-bg-light flex items-center justify-center">
                                    <div className="text-center">
                                        <QRCodeSVG 
                                            size={128} 
                                            value={link.destination || "https://posthog.com"}
                                            imageSettings={{
                                                src: '/static/posthog-icon.svg',
                                                height: 40,
                                                width: 40,
                                                excavate: true
                                            }}
                                        />
                                    </div>
                                </div>
                            </div>
                            
                            <div>
                                <div className="flex justify-between items-center mb-2">
                                    <LemonLabel>Custom Link Preview</LemonLabel>
                                    <LemonSwitch
                                        onChange={() => {}}
                                        checked={false}
                                        label="Enabled"
                                    />
                                </div>
                                
                                <div className="flex gap-1 mt-2">
                                    <LemonButton type="secondary" size="small" active={true}>Global</LemonButton>
                                    <LemonButton type="secondary" size="small">Twitter</LemonButton>
                                    <LemonButton type="secondary" size="small">LinkedIn</LemonButton>
                                    <LemonButton type="secondary" size="small">Facebook</LemonButton>
                                </div>
                                
                                <div className="border rounded-md p-4 mt-2 bg-bg-light flex items-center justify-center">
                                    <div className="text-center">
                                        <div className="text-2xl mb-1">🖼️</div>
                                        <div className="text-sm text-muted">
                                            Upload an image or fill in the fields below
                                        </div>
                                    </div>
                                </div>

                                <div className="mt-2">
                                    <LemonFileInput
                                        accept="image/*"
                                        onChange={(files) => 
                                            setLinkValue('og_image', files?.[0])
                                        }
                                        showUploadedFiles={true}
                                        multiple={false}
                                    />
                                </div>
                                
                                <LemonField name="og_title" label="OG Title">
                                    <LemonInput
                                        placeholder="Add a title..."
                                        fullWidth
                                        autoWidth={false}
                                    />
                                </LemonField>
                                
                                <LemonField name="og_description" label="OG Description">
                                    <LemonTextArea
                                        placeholder="Add a description..."
                                        minRows={2}
                                    />
                                </LemonField>
                            </div>
                        </div>
                    </div>
                </Form>
            </LemonModal>
        </div>
    )
}

export const scene: SceneExport = {
    component: ShortLinksScene,
    logic: shortLinksLogic,
}
