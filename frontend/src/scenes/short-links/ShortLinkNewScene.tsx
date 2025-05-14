import { IconPin as IconLink, IconRefresh, IconChevronDown, IconDownload, IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput, LemonDivider, LemonDropdown, LemonSwitch, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { shortLinksLogic } from './shortLinksLogic'
import { QRCodeSVG } from 'qrcode.react'
import { Form } from 'kea-forms'
import { useState } from 'react'

export function ShortLinkNewScene(): JSX.Element {
    const { newLink } = useValues(shortLinksLogic)
    const {
        setNewLinkDestinationUrl,
        setNewLinkExpirationDate,
        setNewLinkCustomKey,
        setNewLinkTags,
        setNewLinkComments,
        setNewLinkPassword,
        createShortLink,
    } = useActions(shortLinksLogic)
    
    const [domain, setDomain] = useState('posthog.com/e/')

    return (
        <Form
            id="link"
            formKey="link"
            logic={shortLinksLogic}
            props={{ newLink }}
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <PageHeader
                delimited
                buttons={
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            createShortLink()
                            router.actions.push(urls.shortLinks())
                        }}
                        disabled={!newLink.destination_url}
                    >
                        Create link
                    </LemonButton>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-8">
                    <div className="flex-1 space-y-6">
                        <LemonField name="destination_url" label="Destination URL">
                            <LemonInput
                                placeholder="https://example.com"
                                value={newLink.destination_url}
                                onChange={(e) => setNewLinkDestinationUrl(e)}
                                fullWidth
                                autoWidth={false}
                            />
                        </LemonField>
                        
                        <LemonField name="custom_key" label="Short Link">
                            <div className="flex items-center">
                                <div className="flex items-center border rounded px-2 py-1 mr-2 bg-bg-light">
                                    <LemonSelect
                                        fullWidth
                                        options={[
                                            { label: 'posthog.com/e/', value: 'posthog.com/e/' },
                                            { label: 'postho.gg/', value: 'postho.gg/' },
                                            { label: 'hog.gg/', value: 'hog.gg/' }
                                        ]}
                                        value={domain}
                                        onChange={(value) => setDomain(value)}
                                        className="text-muted"
                                    />
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
                        </LemonField>
                        
                        <LemonField name="tags" label="Tags">
                                <LemonInputSelect
                                    placeholder="Select tags..."
                                    mode="multiple"
                                    allowCustomValues
                                    value={newLink.tags || []}
                                    onChange={(tags) => setNewLinkTags(tags)}
                                    fullWidth
                                    autoWidth={false}
                                />
                        </LemonField>

                        <LemonField name="comments" label="Comments">
                            <LemonTextArea
                                placeholder="Add comments"
                                value={newLink.comments || ''}
                                onChange={(e) => setNewLinkComments(e)}
                                minRows={2}
                            />
                        </LemonField>

                        <LemonField name="password" label="Password protection">
                            <LemonInput
                                placeholder="Add a password (optional)"
                                value={newLink.password || ''}
                                onChange={(e) => setNewLinkPassword(e)}
                                type="password"
                                fullWidth
                                autoWidth={false}
                            />
                        </LemonField>

                        <LemonField name="expiration_date" label="Expiration date">
                            <div>
                                <LemonInput
                                    placeholder="Add expiration date (optional)"
                                    value={newLink.expiration_date || ''}
                                    onChange={(e: string) => setNewLinkExpirationDate(e)}
                                    type="text"
                                    fullWidth
                                    autoWidth={false}
                                />
                                <div className="text-muted text-xs mt-1">Format: YYYY-MM-DD</div>
                            </div>
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
                                        value="https://reactjs.org/"
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
            </div>
        </Form>
    )
}

export const scene: SceneExport = {
    component: ShortLinkNewScene,
    logic: shortLinksLogic,
}
