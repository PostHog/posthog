import { JSONContent } from '@tiptap/core'
import { useRef, useState } from 'react'

import { IconChevronDown, IconLock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface MessageInputProps {
    onSendMessage: (content: string, richContent: JSONContent | null, isPrivate: boolean, onSuccess: () => void) => void
    messageSending: boolean
    placeholder?: string
    buttonText?: string
    minRows?: number
    /** Whether to show the "Send as private" option in the dropdown */
    showPrivateOption?: boolean
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder = 'Type your message...',
    buttonText = 'Send',
    minRows = 3,
    showPrivateOption = false,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(true)
    const [isUploading, setIsUploading] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    const handleSubmit = (isPrivate: boolean): void => {
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            onSendMessage(content, richContent, isPrivate, () => {
                editorRef.current?.clear()
                setIsEmpty(true)
            })
        }
    }

    return (
        <div>
            <SupportEditor
                placeholder={placeholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                }}
                onUpdate={(empty) => setIsEmpty(empty)}
                onPressCmdEnter={() => handleSubmit(false)}
                onUploadingChange={setIsUploading}
                disabled={messageSending}
                minRows={minRows}
            />
            <div className="flex justify-end mt-2">
                <LemonButton
                    type="primary"
                    onClick={() => handleSubmit(false)}
                    loading={messageSending}
                    disabledReason={isEmpty ? 'No message' : isUploading ? 'Uploading image...' : undefined}
                    sideAction={
                        showPrivateOption
                            ? {
                                  icon: <IconChevronDown />,
                                  dropdown: {
                                      placement: 'bottom-end',
                                      matchWidth: false,
                                      overlay: (
                                          <LemonMenuOverlay
                                              items={[
                                                  {
                                                      label: 'Send as private',
                                                      icon: <IconLock />,
                                                      tooltip:
                                                          'Private messages are only visible to your team, not to the customer',
                                                      onClick: () => handleSubmit(true),
                                                  },
                                              ]}
                                          />
                                      ),
                                  },
                              }
                            : undefined
                    }
                >
                    {buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
