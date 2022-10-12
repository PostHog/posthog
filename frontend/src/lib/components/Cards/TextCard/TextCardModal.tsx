import { DashboardType } from '~/types'
import { textCardModalLogic } from 'lib/components/Cards/TextCard/textCardModalLogic'
import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/components/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { Field, Form } from 'kea-forms'
import { LemonTextMarkdown } from 'lib/components/LemonTextArea/LemonTextArea'
import React from 'react'

export function TextCardModal({
    isOpen,
    onClose,
    dashboard,
    textTileId,
}: {
    isOpen: boolean
    onClose: () => void
    dashboard: DashboardType
    textTileId: number | 'new' | null
}): JSX.Element {
    const modalLogic = textCardModalLogic({ dashboard, textTileId: textTileId ?? 'new', onClose })
    const { isTextTileSubmitting } = useValues(modalLogic)
    const { submitTextTile, resetTextTile } = useActions(modalLogic)

    const handleClose = (): void => {
        resetTextTile()
        onClose()
    }

    return (
        <LemonModal
            closable={true}
            isOpen={isOpen}
            title={''}
            onClose={handleClose}
            footer={
                <>
                    <LemonButton disabled={isTextTileSubmitting} type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabled={isTextTileSubmitting}
                        loading={isTextTileSubmitting}
                        form="text-tile-form"
                        htmlType="submit"
                        type="primary"
                        onClick={submitTextTile}
                        data-attr={textTileId === 'new' ? 'save-new-text-tile' : 'edit-text-tile-text'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={textCardModalLogic}
                props={{ dashboard: dashboard, textTileId: textTileId }}
                formKey={'textTile'}
                id="text-tile-form"
                className=""
                enableFormOnSubmit
            >
                <Field name="body" label="">
                    {({ value, onChange }) => (
                        <LemonTextMarkdown data-attr={'text-card-edit-area'} value={value} onChange={onChange} />
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}
