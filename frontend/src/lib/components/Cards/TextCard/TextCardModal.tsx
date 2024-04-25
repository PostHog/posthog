import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { textCardModalLogic } from 'lib/components/Cards/TextCard/textCardModalLogic'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, DashboardType } from '~/types'

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
    const { isTextTileSubmitting, textTileValidationErrors } = useValues(modalLogic)
    const { submitTextTile, resetTextTile } = useActions(modalLogic)

    const { hasAvailableFeature } = useValues(userLogic)

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
            footer={
                <>
                    <LemonButton
                        disabledReason={isTextTileSubmitting ? 'Cannot cancel card creation in progress' : null}
                        type="secondary"
                        onClick={handleClose}
                    >
                        Cancel
                    </LemonButton>
                    {hasAvailableFeature(AvailableFeature.TEAM_COLLABORATION) && (
                        <LemonButton
                            disabledReason={textTileValidationErrors.body as string | null}
                            loading={isTextTileSubmitting}
                            form="text-tile-form"
                            htmlType="submit"
                            type="primary"
                            onClick={submitTextTile}
                            data-attr={textTileId === 'new' ? 'save-new-text-tile' : 'edit-text-tile-text'}
                        >
                            Save
                        </LemonButton>
                    )}
                </>
            }
        >
            <Form
                logic={textCardModalLogic}
                props={{ dashboard, textTileId }}
                formKey="textTile"
                id="text-tile-form"
                className=""
                enableFormOnSubmit
            >
                <PayGateMini feature={AvailableFeature.TEAM_COLLABORATION}>
                    <Field name="body" label="">
                        <LemonTextAreaMarkdown data-attr="text-card-edit-area" />
                    </Field>
                </PayGateMini>
            </Form>
        </LemonModal>
    )
}
