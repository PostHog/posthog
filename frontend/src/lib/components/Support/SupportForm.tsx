import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { LemonInput, lemonToast } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { SUPPORT_TICKET_TEMPLATES, supportLogic } from './supportLogic'

export function SupportForm(): JSX.Element | null {
    const { sendSupportRequest } = useValues(supportLogic)
    const { setSendSupportRequestValue } = useActions(supportLogic)
    const { objectStorageAvailable } = useValues(preflightLogic)
    // the support model can be shown when logged out, file upload is not offered to anonymous users
    const { user } = useValues(userLogic)
    // only allow authentication issues for logged out users

    const dropRef = useRef<HTMLDivElement>(null)

    const handlePaste = (e: React.ClipboardEvent<HTMLDivElement>): void => {
        const items = e.clipboardData?.items
        if (!items) {
            return
        }

        // Convert DataTransferItemList to array for iteration
        const itemsArray = Array.from(items)
        for (const item of itemsArray) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile()
                if (file) {
                    setFilesToUpload([...filesToUpload, file])
                }
            }
        }
    }

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            setSendSupportRequestValue('message', sendSupportRequest.message + `\n\nAttachment "${fileName}": ${url}`)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    return (
        <Form
            logic={supportLogic}
            formKey="sendSupportRequest"
            id="support-modal-form"
            enableFormOnSubmit
            className="deprecated-space-y-4"
        >
            {!user && (
                <>
                    <LemonField name="name" label="Name">
                        <LemonInput data-attr="name" placeholder="Jane" />
                    </LemonField>
                    <LemonField name="email" label="Email">
                        <LemonInput data-attr="email" placeholder="your@email.com" />
                    </LemonField>
                </>
            )}
            <LemonField name="message" label="What can we help you with?">
                {(props) => (
                    <div ref={dropRef} className="flex flex-col gap-2" onPaste={handlePaste}>
                        <LemonTextArea
                            placeholder={
                                SUPPORT_TICKET_TEMPLATES[sendSupportRequest.kind] ?? SUPPORT_TICKET_TEMPLATES['support']
                            }
                            data-attr="support-form-content-input"
                            minRows={5}
                            {...props}
                        />
                        {objectStorageAvailable && !!user && (
                            <LemonFileInput
                                accept="image/*"
                                multiple={false}
                                alternativeDropTargetRef={dropRef}
                                onChange={setFilesToUpload}
                                loading={uploading}
                                value={filesToUpload}
                            />
                        )}
                    </div>
                )}
            </LemonField>
        </Form>
    )
}
