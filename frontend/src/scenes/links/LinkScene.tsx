import { IconCopy, IconDownload } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTag, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { QRCodeSVG } from 'qrcode.react'
import { SceneExport } from 'scenes/sceneTypes'

import { linkConfigurationLogic } from './linkConfigurationLogic'

const SOON_TAG = (
    <LemonTag type="completion" size="small" className="ml-2">
        SOON
    </LemonTag>
)

const PAID_TAG = (
    <LemonTag type="success" size="small" className="ml-2">
        PAID
    </LemonTag>
)

const LabelWithTag = ({ label, paid }: { label: string; paid?: boolean }): JSX.Element => {
    return (
        <div>
            <span>{label}</span>
            {SOON_TAG}
            {paid && PAID_TAG}
        </div>
    )
}

export function LinkScene({ id }: { id?: string } = {}): JSX.Element {
    const logic = linkConfigurationLogic({ id: id ?? 'new' })
    const { link, isLinkSubmitting, linkLoading } = useValues(logic)
    const { submitLink } = useActions(logic)

    // While loading, show a spinner
    if (linkLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    const isNew = id === 'new'
    const buttonText = isNew ? 'Create link' : 'Update link'

    const fullLink = link?.id ? `https://${link.short_link_domain}/${link.short_code}` : 'https://phog.gg'

    return (
        <Form
            id="link"
            formKey="link"
            logic={linkConfigurationLogic}
            props={{ id: id ?? 'new' }}
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <PageHeader
                delimited
                buttons={
                    <LemonButton type="primary" onClick={submitLink} loading={isLinkSubmitting}>
                        {buttonText}
                    </LemonButton>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-8">
                    <div className="flex-1 space-y-6">
                        <LemonField name="redirect_url" label="Destination URL">
                            <LemonInput
                                placeholder="https://loooooooooooooong.posthog.com/blog/"
                                fullWidth
                                autoWidth={false}
                            />
                        </LemonField>

                        <div className="flex flex-col gap-2">
                            <LemonLabel>Link</LemonLabel>
                            <div className="flex gap-1 items-center">
                                <LemonField name="short_link_domain">
                                    <LemonSelect
                                        options={[
                                            { label: 'phog.gg', value: 'phog.gg' },
                                            {
                                                label: <LabelWithTag label="postho.gg" />,
                                                value: 'postho.gg',
                                                disabledReason: 'Coming soon...',
                                            },
                                            {
                                                label: <LabelWithTag label="hog.gg" />,
                                                value: 'hog.gg',
                                                disabledReason: 'Coming soon...',
                                            },
                                            {
                                                label: <LabelWithTag label="Custom (BYOD)" paid />,
                                                value: 'custom',
                                                disabledReason: 'Coming soon...',
                                            },
                                        ]}
                                        className="text-muted"
                                    />
                                </LemonField>
                                <span className="text-muted">/</span>
                                <LemonField name="short_code" className="w-full">
                                    <LemonInput fullWidth placeholder="short" className="flex-1" autoWidth={false} />
                                </LemonField>
                            </div>
                        </div>

                        <LemonField name="description" label="Description">
                            <LemonTextArea
                                placeholder="Add a description so that you can easily identify this link"
                                minRows={2}
                            />
                        </LemonField>
                    </div>

                    <LemonDivider vertical />

                    <div className="flex-1 space-y-6 max-w-80">
                        <div>
                            <div className="flex justify-between items-center">
                                <LemonLabel>
                                    <span className="flex items-center gap-1">QR Code</span>
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
                                    {/* TODO: QR code doesnt take the current form data into consideration, we need to update this to include that */}
                                    <QRCodeSVG
                                        size={128}
                                        value={fullLink}
                                        level="H"
                                        imageSettings={{
                                            src: '/static/posthog-icon.svg',
                                            height: 40,
                                            width: 40,
                                            excavate: true,
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
    logic: linkConfigurationLogic,
    paramsToProps: ({ params }): (typeof linkConfigurationLogic)['props'] => ({ id: params.id }),
}
