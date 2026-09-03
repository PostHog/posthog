import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { textCardModalLogic } from 'lib/components/Cards/TextCard/textCardModalLogic'
import type { TextCardModalProps } from 'lib/components/Cards/TextCard/textCardModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { DashboardTileIdOrNew, DashboardType, QueryBasedInsightModel } from '~/types'

import {
    DEFAULT_SEPARATOR_TILE_THICKNESS,
    getSeparatorTileThickness,
    separatorTileToMarkdown,
    separatorTileThicknessClassName,
    type SeparatorTileThickness,
} from './separatorTileUtils'

const SEPARATOR_THICKNESS_OPTIONS = [
    { value: 'thin', label: 'Thin' },
    { value: 'medium', label: 'Medium' },
    { value: 'thick', label: 'Thick' },
] satisfies { value: SeparatorTileThickness; label: string }[]

export function SeparatorTileModal({
    isOpen,
    onClose,
    dashboard,
    separatorTileId,
}: {
    isOpen: boolean
    onClose: () => void
    dashboard: DashboardType<QueryBasedInsightModel>
    separatorTileId: DashboardTileIdOrNew
}): JSX.Element {
    const isNewTile = separatorTileId === null
    const modalLogicProps: TextCardModalProps = {
        dashboard,
        textTileId: separatorTileId,
        onClose,
        tileType: 'separator',
    }
    const modalLogic = textCardModalLogic(modalLogicProps)
    const { isTextTileSubmitting, textTile } = useValues(modalLogic)
    const { resetTextTile, setTextTileValues } = useActions(modalLogic)
    const thickness = getSeparatorTileThickness(textTile.body) ?? DEFAULT_SEPARATOR_TILE_THICKNESS

    const handleClose = (): void => {
        resetTextTile()
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={isNewTile ? 'Add separator' : 'Edit separator'}
            description="Separate dashboard sections with a horizontal line."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isTextTileSubmitting ? 'Cannot cancel in progress' : null}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form="separator-tile-form"
                        htmlType="submit"
                        loading={isTextTileSubmitting}
                        data-attr={isNewTile ? 'save-new-separator-tile' : 'edit-separator-tile'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={textCardModalLogic}
                props={modalLogicProps}
                formKey="textTile"
                id="separator-tile-form"
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-4">
                    <LemonRadio<SeparatorTileThickness>
                        value={thickness}
                        onChange={(value) => setTextTileValues({ body: separatorTileToMarkdown(value) })}
                        options={SEPARATOR_THICKNESS_OPTIONS}
                        orientation="horizontal"
                        aria-label="Separator thickness"
                    />
                    <div className="rounded bg-surface-secondary p-4">
                        <hr
                            className={clsx(
                                'm-0 w-full border-0 bg-border',
                                separatorTileThicknessClassName(thickness)
                            )}
                        />
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
