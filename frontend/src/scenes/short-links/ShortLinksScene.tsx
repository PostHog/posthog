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

import { ProductKey } from '~/types'

import { shortLinksLogic } from './shortLinksLogic'

export function ShortLinksScene(): JSX.Element {
    const { shortLinksLoading } = useValues(shortLinksLogic)
    const {} = useActions(shortLinksLogic)
    
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)

    const baseUrl = `${window.location.origin}/e`

    const columns = [
        {
            title: 'Short URL',
            dataIndex: 'key',
            render: function RenderKey(key: string | any) {
                if (!key) {
                    return null
                }
                const shortUrl = `${baseUrl}/${key}`
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
            dataIndex: 'destination_url' as keyof ShortLink,
            render: function RenderDestination(destination: string | any) {
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
            render: function RenderDate(date: string | any) {
                if (!date) {
                    return null
                }
                return dayjs(date).format('MMM D, YYYY')
            },
        },
        {
            title: 'Expires',
            dataIndex: 'expiration_date' as keyof ShortLink,
            render: function RenderExpiry(date: string | any) {
                if (!date) {
                    return <span className="text-muted">Never</span>
                }
                return dayjs(date).format('MMM D, YYYY')
            },
        },
        {
            title: 'Actions',
            dataIndex: 'key' as keyof ShortLink,
            render: function RenderActions(key: string | any, record: ShortLink) {
                if (!key) {
                    return null
                }
                return (
                    <div className="flex gap-2">
                        <LemonButton
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => setEditingLink(record)}
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
                                                {baseUrl}/{key}
                                            </code>
                                            ?
                                        </>
                                    ),
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Delete',
                                        onClick: () => deleteShortLink(key),
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
                    rowKey="key"
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
                        rowKey="key"
                        pagination={{ pageSize: 10 }}
                        nouns={['expired link', 'expired links']}
                    />
                </>
            )}

            {/* Create short link modal */}
            <LemonModal
                isOpen={isCreateModalOpen}
                onClose={() => setIsCreateModalOpen(false)}
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
                                    createShortLink()
                                    setIsCreateModalOpen(false)
                                }}
                                type="primary"
                                disabled={!newLink.destination_url}
                            >
                                Create link
                            </LemonButton>
                        </div>
                    </div>
                }
            >
                <div className="flex gap-8">
                    {/* Left side */}
                    <div className="flex-1 space-y-6">
                        <div>
                            <LemonLabel>Destination URL</LemonLabel>
                            <div className="flex items-center">
                                <LemonInput
                                    placeholder="https://example.com"
                                    value={newLink.destination_url}
                                    onChange={(e) => setNewLinkDestinationUrl(e)}
                                    fullWidth
                                    autoWidth={false}
                                />
                                <LemonButton
                                    icon={<IconLink />}
                                    size="small"
                                    className="ml-2"
                                />
                            </div>
                        </div>
                        
                        <div>
                            <LemonLabel>Short Link</LemonLabel>
                            <div className="flex items-center">
                                <div className="flex items-center border rounded px-2 py-1 mr-2 bg-bg-light">
                                    <span className="text-muted">posthog.com/e/</span>
                                    <LemonButton
                                        icon={<IconChevronDown />}
                                        size="small"
                                        status="alt"
                                    />
                                </div>
                                <LemonInput
                                    placeholder="posthog-cdp"
                                    value={newLink.custom_key || ''}
                                    onChange={(e) => setNewLinkCustomKey(e)}
                                    className="flex-1"
                                    autoWidth={false}
                                />
                                <LemonButton
                                    icon={<IconRefresh />}
                                    size="small"
                                    className="ml-2"
                                />
                            </div>
                        </div>
                        
                        <div>
                            <div className="flex justify-between">
                                <LemonLabel>Tags</LemonLabel>
                                <LemonButton status="alt" size="small">Manage</LemonButton>
                            </div>
                            <LemonInputSelect
                                placeholder="Select tags..."
                                mode="multiple"
                                allowCustomValues
                                value={newLink.tags || []}
                                onChange={(tags) => setNewLinkTags(tags)}
                                fullWidth
                                autoWidth={false}
                            />
                        </div>
                        
                        <div>
                            <LemonLabel>Comments</LemonLabel>
                            <LemonTextArea
                                placeholder="Add comments"
                                value={newLink.comments || ''}
                                onChange={(e) => setNewLinkComments(e)}
                                minRows={2}
                            />
                        </div>
                    </div>

                    <LemonDivider vertical />
                    
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
                                    <div className="text-2xl mb-1">📱</div>
                                    <div className="text-sm text-muted">QR Code will appear here</div>
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
                                    onChange={(files) => setNewLinkOgImage(files?.[0])}
                                    showUploadedFiles={true}
                                    multiple={false}
                                />
                            </div>
                            
                            <div className="mt-2">
                                <LemonLabel>OG Title</LemonLabel>
                                <LemonInput
                                    placeholder="Add a title..."
                                    value={newLink.og_title || ''}
                                    onChange={(e) => setNewLinkOgTitle(e)}
                                    fullWidth
                                    autoWidth={false}
                                />
                            </div>
                            
                            <div className="mt-2">
                                <LemonLabel>OG Description</LemonLabel>
                                <LemonTextArea
                                    placeholder="Add a description..."
                                    value={newLink.og_description || ''}
                                    onChange={(e) => setNewLinkOgDescription(e)}
                                    minRows={2}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </LemonModal>

            {/* Edit short link modal */}
            {editingLink && (
                <LemonModal
                    isOpen={!!editingLink}
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
                    onClose={() => setEditingLink(null)}
                    width={900}
                    closable={true}
                    footer={
                        <div className="flex justify-end">
                            <LemonButton
                                onClick={() => setEditingLink(null)} 
                                type="secondary"
                                className="mr-2"
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    if (editingLink) {
                                        updateShortLink(editingLink.key, {
                                            destination_url: editingLink.destination_url,
                                            expiration_date: editingLink.expiration_date,
                                            custom_key: editingLink.custom_key,
                                            tags: editingLink.tags,
                                            comments: editingLink.comments,
                                            folder: editingLink.folder,
                                            password: editingLink.password,
                                            og_title: editingLink.og_title,
                                            og_description: editingLink.og_description,
                                            og_image: editingLink.og_image,
                                            utm_params: editingLink.utm_params,
                                            targeting: editingLink.targeting,
                                        })
                                    }
                                }}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                >
                    <div className="flex gap-8">
                        {/* Left side */}
                        <div className="flex-1 space-y-6">
                            <div>
                                <LemonLabel>Short URL</LemonLabel>
                                <div className="flex items-center border rounded px-2 py-1 bg-bg-light font-mono">
                                    {baseUrl}/{editingLink.key}
                                    <LemonButton
                                        icon={<IconCopy />}
                                        size="small"
                                        className="ml-2"
                                        onClick={() => {
                                            void navigator.clipboard.writeText(`${baseUrl}/${editingLink.key}`)
                                        }}
                                    />
                                </div>
                            </div>
                            
                            <div>
                                <LemonLabel>Destination URL</LemonLabel>
                                <div className="flex items-center">
                                    <LemonInput
                                        placeholder="https://example.com"
                                        value={editingLink.destination_url}
                                        onChange={(e) =>
                                            setEditingLink({
                                                ...editingLink,
                                                destination_url: e,
                                            })
                                        }
                                        fullWidth
                                        autoWidth={false}
                                    />
                                    <LemonButton
                                        icon={<IconLink />}
                                        size="small"
                                        className="ml-2"
                                    />
                                </div>
                            </div>
                            
                            <div>
                                <LemonLabel>Short Link</LemonLabel>
                                <div className="flex items-center">
                                    <div className="flex items-center border rounded px-2 py-1 mr-2 bg-bg-light">
                                        <span className="text-muted">posthog.com/e/</span>
                                        <LemonButton
                                            icon={<IconChevronDown />}
                                            size="small"
                                            status="alt"
                                        />
                                    </div>
                                    <LemonInput
                                        placeholder="custom-key"
                                        value={editingLink.custom_key || ''}
                                        onChange={(e) =>
                                            setEditingLink({
                                                ...editingLink,
                                                custom_key: e,
                                            })
                                        }
                                        className="flex-1"
                                        autoWidth={false}
                                    />
                                </div>
                            </div>
                            
                            <div>
                                <div className="flex justify-between">
                                    <LemonLabel>Tags</LemonLabel>
                                    <LemonButton status="alt" size="small">Manage</LemonButton>
                                </div>
                                <LemonInputSelect
                                    placeholder="Select tags..."
                                    mode="multiple"
                                    allowCustomValues
                                    value={editingLink.tags || []}
                                    onChange={(tags) =>
                                        setEditingLink({
                                            ...editingLink,
                                            tags,
                                        })
                                    }
                                    fullWidth
                                    autoWidth={false}
                                />
                            </div>
                            
                            <div>
                                <LemonLabel>Comments</LemonLabel>
                                <LemonTextArea
                                    placeholder="Add comments"
                                    value={editingLink.comments || ''}
                                    onChange={(e) =>
                                        setEditingLink({
                                            ...editingLink,
                                            comments: e,
                                        })
                                    }
                                    minRows={2}
                                />
                            </div>
                            
                            <div>
                                <LemonLabel>Folder</LemonLabel>
                                <LemonSelect
                                    options={[
                                        { value: 'Links', label: 'Links' },
                                        { value: 'Marketing', label: 'Marketing' },
                                        { value: 'Social', label: 'Social' },
                                    ]}
                                    value={editingLink.folder || 'Links'}
                                    onChange={(val) => 
                                        val && setEditingLink({
                                            ...editingLink,
                                            folder: val,
                                        })
                                    }
                                    fullWidth
                                />
                            </div>
                            
                            <div>
                                <LemonLabel>Expiration Date (optional)</LemonLabel>
                                <LemonInput
                                    type="text"
                                    placeholder="YYYY-MM-DD"
                                    value={editingLink.expiration_date || ''}
                                    onChange={(e) =>
                                        setEditingLink({
                                            ...editingLink,
                                            expiration_date: e || undefined,
                                        })
                                    }
                                    fullWidth
                                    autoWidth={false}
                                />
                                <div className="text-muted text-xs mt-1">
                                    The link will stop working after this date
                                </div>
                            </div>
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
                                        <div className="text-2xl mb-1">📱</div>
                                        <div className="text-sm text-muted">QR Code will appear here</div>
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
                                
                                {editingLink.og_image ? (
                                    <div className="border rounded-md p-2 mt-2">
                                        <img 
                                            src={typeof editingLink.og_image === 'string' ? editingLink.og_image : URL.createObjectURL(editingLink.og_image)} 
                                            alt="Preview" 
                                            className="w-full h-32 object-cover rounded"
                                        />
                                        <div className="mt-2">
                                            <div className="font-medium">{editingLink.og_title || 'Title'}</div>
                                            <div className="text-sm text-gray-500">{editingLink.og_description || 'Description'}</div>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="border rounded-md p-4 mt-2 bg-bg-light flex items-center justify-center">
                                        <div className="text-center">
                                            <div className="text-2xl mb-1">🖼️</div>
                                            <div className="text-sm text-muted">
                                                Upload an image or fill in the fields below
                                            </div>
                                        </div>
                                    </div>
                                )}

                                <div className="mt-2">
                                    <LemonFileInput
                                        accept="image/*"
                                        onChange={(files) => 
                                            setEditingLink({
                                                ...editingLink,
                                                og_image: files?.[0],
                                            })
                                        }
                                        showUploadedFiles={true}
                                        multiple={false}
                                    />
                                </div>
                                
                                <div className="mt-2">
                                    <LemonLabel>OG Title</LemonLabel>
                                    <LemonInput
                                        placeholder="Add a title..."
                                        value={editingLink.og_title || ''}
                                        onChange={(e) =>
                                            setEditingLink({
                                                ...editingLink,
                                                og_title: e,
                                            })
                                        }
                                        fullWidth
                                        autoWidth={false}
                                    />
                                </div>
                                
                                <div className="mt-2">
                                    <LemonLabel>OG Description</LemonLabel>
                                    <LemonTextArea
                                        placeholder="Add a description..."
                                        value={editingLink.og_description || ''}
                                        onChange={(e) =>
                                            setEditingLink({
                                                ...editingLink,
                                                og_description: e,
                                            })
                                        }
                                        minRows={2}
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                </LemonModal>
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: ShortLinksScene,
    logic: shortLinksLogic,
}
