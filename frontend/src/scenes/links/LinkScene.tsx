import { IconDownload, IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { linksLogic } from './linksLogic'
import { QRCodeSVG } from 'qrcode.react'
import { Form } from 'kea-forms'

export function LinkScene(): JSX.Element {
    const { link } = useValues(linksLogic)
    const { submitLink } = useActions(linksLogic)

    return (
        <Form
            id="link"
            formKey="link"
            logic={linksLogic}
            props={{ link }}
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <PageHeader
                delimited
                buttons={
                    <LemonButton
                        type="primary"
                        onClick={submitLink}
                    >
                        Create link
                    </LemonButton>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-8">
                    <div className="flex-1 space-y-6">
                        <LemonField name="destination" label="Destination URL">
                            <LemonInput
                                placeholder="https://posthog.com/links"
                                fullWidth
                                autoWidth={false}
                            />
                        </LemonField>

                        <div className="flex flex-col gap-2">
                            <LemonLabel>Link</LemonLabel>
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

                        <LemonField name="description" label="Comments">
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
    component: LinkScene,
    logic: linksLogic,
}
