import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { ButtonTileCard } from 'lib/components/Cards/ButtonTileCard/ButtonTileCard'
import { buttonTileCardModalLogic } from 'lib/components/Cards/ButtonTileCard/buttonTileCardModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { DashboardPlacement, DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

export function ButtonTileCardModal({
    isOpen,
    onClose,
    dashboard,
    buttonTileId,
}: {
    isOpen: boolean
    onClose: () => void
    dashboard: DashboardType<QueryBasedInsightModel>
    buttonTileId: number | 'new' | null
}): JSX.Element {
    const modalLogic = buttonTileCardModalLogic({ dashboard, buttonTileId: buttonTileId ?? 'new', onClose })
    const { buttonTile, isButtonTileSubmitting, buttonTileValidationErrors } = useValues(modalLogic)
    const { submitButtonTile, resetButtonTile } = useActions(modalLogic)

    const handleClose = (): void => {
        resetButtonTile()
        onClose()
    }

    const firstError = buttonTileValidationErrors.url || buttonTileValidationErrors.text
    const previewTile: DashboardTile<QueryBasedInsightModel> = {
        id: buttonTileId === 'new' ? 0 : (buttonTileId ?? 0),
        color: null,
        button_tile: { ...buttonTile, text: buttonTile.text || 'Click me' },
        transparent_background: buttonTile.transparent_background,
    }

    return (
        <LemonModal
            closable={true}
            isOpen={isOpen}
            title={buttonTileId === 'new' ? 'Add link' : 'Edit link'}
            onClose={handleClose}
            footer={
                <>
                    <LemonButton
                        disabledReason={isButtonTileSubmitting ? 'Cannot cancel in progress' : null}
                        type="secondary"
                        onClick={handleClose}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={firstError as string | null}
                        loading={isButtonTileSubmitting}
                        form="button-tile-form"
                        htmlType="submit"
                        type="primary"
                        onClick={submitButtonTile}
                        data-attr={buttonTileId === 'new' ? 'save-new-button-tile' : 'edit-button-tile'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={buttonTileCardModalLogic}
                props={{ dashboard, buttonTileId }}
                formKey="buttonTile"
                id="button-tile-form"
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    <Field name="url" label="URL">
                        <LemonInput
                            placeholder="https://example.com or /dashboards"
                            data-attr="button-tile-url"
                            autoFocus
                        />
                    </Field>
                    <Field name="text" label="Link text">
                        <LemonInput placeholder="Click me" data-attr="button-tile-text" />
                    </Field>
                    <Field name="placement" label="Placement within tile">
                        <LemonSegmentedButton
                            options={[
                                { value: 'left', label: 'Left' },
                                { value: 'right', label: 'Right' },
                            ]}
                            data-attr="button-tile-placement"
                        />
                    </Field>
                    <Field name="style" label="Style">
                        <LemonSegmentedButton
                            options={[
                                { value: 'primary', label: 'Primary' },
                                { value: 'secondary', label: 'Secondary' },
                            ]}
                            data-attr="button-tile-style"
                        />
                    </Field>
                    <Field name="transparent_background" label="">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Transparent background"
                                data-attr="button-tile-transparent-background"
                            />
                        )}
                    </Field>
                    <div>
                        <h4 className="mb-2">Preview</h4>
                        <div className="pointer-events-none rounded bg-surface-secondary p-3">
                            <ButtonTileCard
                                buttonTile={previewTile}
                                placement={DashboardPlacement.Dashboard}
                                showEditingControls={false}
                                className="h-32 overflow-hidden [&_.LemonButton]:max-w-64 [&_.LemonButton__content]:truncate"
                            />
                        </div>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
