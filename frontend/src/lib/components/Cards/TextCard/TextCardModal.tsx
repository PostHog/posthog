import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { useState } from 'react'

import { isTextCardMarkdownRoundTripSafe } from 'lib/components/Cards/TextCard/textCardMarkdown'
import { TextCardMarkdownEditor } from 'lib/components/Cards/TextCard/TextCardMarkdownEditor'
import { textCardModalLogic } from 'lib/components/Cards/TextCard/textCardModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

import { DashboardType, QueryBasedInsightModel } from '~/types'

export function TextCardModal({
    isOpen,
    onClose,
    dashboard,
    textTileId,
}: {
    isOpen: boolean
    onClose: () => void
    dashboard: DashboardType<QueryBasedInsightModel>
    textTileId: number | 'new' | null
}): JSX.Element {
    const modalLogic = textCardModalLogic({ dashboard, textTileId: textTileId ?? 'new', onClose })
    const { isTextTileSubmitting, textTileValidationErrors, textTile } = useValues(modalLogic)
    const { resetTextTile } = useActions(modalLogic)
    const [initialBody] = useState(() =>
        textTileId && textTileId !== 'new'
            ? dashboard.tiles?.find((tile) => tile.id === textTileId)?.text?.body || ''
            : ''
    )
    const shouldUseLegacyMarkdownEditor = !isTextCardMarkdownRoundTripSafe(initialBody)
    const hasUnsavedInput = (textTile?.body || '') !== initialBody

    const handleClose = (): void => {
        resetTextTile()
        onClose()
    }

    return (
        <LemonModal
            closable={true}
            isOpen={isOpen}
            title=""
            onClose={handleClose}
            hasUnsavedInput={hasUnsavedInput}
            className="min-w-full lg:min-w-6xl"
            footer={
                <>
                    <LemonButton
                        disabledReason={isTextTileSubmitting ? 'Cannot cancel card creation in progress' : null}
                        type="secondary"
                        onClick={handleClose}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={textTileValidationErrors.body as string | null}
                        loading={isTextTileSubmitting}
                        form="text-tile-form"
                        htmlType="submit"
                        type="primary"
                        data-attr={textTileId === 'new' ? 'save-new-text-tile' : 'edit-text-tile-text'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={textCardModalLogic}
                props={{ dashboard, textTileId: textTileId ?? 'new', onClose }}
                formKey="textTile"
                id="text-tile-form"
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    <Field name="body" label="">
                        {({ value, onChange }) =>
                            shouldUseLegacyMarkdownEditor ? (
                                <LemonTextAreaMarkdown
                                    value={value}
                                    onChange={onChange}
                                    maxLength={4000}
                                    minRows={8}
                                    maxRows={36}
                                    data-attr="text-card-edit-area"
                                />
                            ) : (
                                <TextCardMarkdownEditor value={value} onChange={onChange} minRows={8} maxRows={36} />
                            )
                        }
                    </Field>
                    <Field name="transparent_background" label="">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Transparent background"
                                data-attr="text-card-transparent-background"
                            />
                        )}
                    </Field>
                </div>
            </Form>
        </LemonModal>
    )
}
