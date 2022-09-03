import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'
import clsx from 'clsx'
import { DashboardTextTile, DashboardType, InsightColor } from '~/types'
import { LemonButton, LemonDivider, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'
import { dashboardTextTileModalLogic } from './dashboardTextTileModalLogic'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export function TextTileModal({
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
    const modalLogic = dashboardTextTileModalLogic({ dashboard, textTileId: textTileId ?? 'new', onClose })
    const { isTextTileSubmitting } = useValues(modalLogic)
    const { submitTextTile } = useActions(modalLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            title={textTileId === 'new' ? 'Add text to the Dashboard' : 'Edit text'}
            onClose={onClose}
            footer={
                <>
                    <LemonButton disabled={isTextTileSubmitting} type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabled={isTextTileSubmitting}
                        loading={isTextTileSubmitting}
                        form="text-tile-form"
                        htmlType="submit"
                        type="primary"
                        onClick={submitTextTile}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            {}
            <Form
                logic={dashboardTextTileModalLogic}
                props={{ dashboard: dashboard, textTileId: textTileId }}
                formKey={'textTile'}
                id="text-tile-form"
                className="space-y-2"
                enableFormOnSubmit
            >
                <Field name="body" label="Body">
                    {({ value, onChange }) => (
                        <LemonTextArea autoFocus value={value} onChange={(newValue) => onChange(newValue)} />
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId: string | number
    textTile: DashboardTextTile
    children?: JSX.Element
}

function TextCardHeader({
    dashboardId,
    textTile,
    showEditingControls,
}: {
    dashboardId: string | number
    textTile: DashboardTextTile
    showEditingControls: boolean
}): JSX.Element {
    const { push } = useActions(router)

    return (
        <div className="min-h-4 flex flex-col items-center w-full">
            <div className="w-full flex flex-row pt-2 px-2">
                {textTile.color &&
                    textTile.color !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('DashboardCard__ribbon', textTile.color)} />
                    )}
                <div className="flex flex-1 justify-end">
                    {showEditingControls && (
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        status="stealth"
                                        fullWidth
                                        onClick={() => push(urls.dashboardTextTile(dashboardId, textTile.id))}
                                    >
                                        Edit text
                                    </LemonButton>
                                </>
                            }
                        />
                    )}
                </div>
            </div>
            <LemonDivider />
        </div>
    )
}

export function TextCardInternal(
    { textTile, showResizeHandles, canResizeWidth, children, className, dashboardId, ...divProps }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className={clsx('TextCard border rounded', className)} data-attr="text-card" {...divProps} ref={ref}>
            <TextCardHeader textTile={textTile} dashboardId={dashboardId} showEditingControls={true} />
            <Textfit mode="single" min={32} max={120}>
                <div>{textTile.body}</div>
            </Textfit>
            {showResizeHandles && (
                <>
                    {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                    <ResizeHandle1D orientation="horizontal" />
                    {canResizeWidth ? <ResizeHandle2D /> : null}
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef(TextCardInternal) as typeof TextCardInternal
