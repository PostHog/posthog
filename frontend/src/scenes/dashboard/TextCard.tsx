import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'
import clsx from 'clsx'
import { DashboardTextTile, DashboardType, InsightColor, InsightModel } from '~/types'
import { LemonButton, LemonButtonWithPopup, LemonDivider, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'
import { dashboardTextTileModalLogic } from './dashboardTextTileModalLogic'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Splotch, SplotchColor } from 'lib/components/icons/Splotch'
import { capitalizeFirstLetter } from 'lib/utils'

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
    updateColor?: (newColor: InsightModel['color']) => void
    removeFromDashboard?: () => void
}

function TextCardHeader({
    dashboardId,
    textTile,
    showEditingControls,
    updateColor,
    removeFromDashboard,
}: {
    dashboardId: string | number
    textTile: DashboardTextTile
    showEditingControls: boolean
    updateColor?: (newColor: InsightModel['color']) => void
    removeFromDashboard?: () => void
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

                                    {updateColor && (
                                        <LemonButtonWithPopup
                                            status="stealth"
                                            popup={{
                                                overlay: Object.values(InsightColor).map((availableColor) => (
                                                    <LemonButton
                                                        key={availableColor}
                                                        active={
                                                            availableColor === (textTile.color || InsightColor.White)
                                                        }
                                                        status="stealth"
                                                        onClick={() => updateColor(availableColor)}
                                                        icon={
                                                            availableColor !== InsightColor.White ? (
                                                                <Splotch
                                                                    color={availableColor as string as SplotchColor}
                                                                />
                                                            ) : null
                                                        }
                                                        fullWidth
                                                    >
                                                        {availableColor !== InsightColor.White
                                                            ? capitalizeFirstLetter(availableColor)
                                                            : 'No color'}
                                                    </LemonButton>
                                                )),
                                                placement: 'right-start',
                                                fallbackPlacements: ['left-start'],
                                                actionable: true,
                                            }}
                                            fullWidth
                                        >
                                            Set color
                                        </LemonButtonWithPopup>
                                    )}
                                    <LemonDivider />
                                    {removeFromDashboard && (
                                        <LemonButton status="danger" onClick={removeFromDashboard} fullWidth>
                                            Remove from dashboard
                                        </LemonButton>
                                    )}
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
    {
        textTile,
        showResizeHandles,
        canResizeWidth,
        children,
        className,
        dashboardId,
        updateColor,
        removeFromDashboard,
        ...divProps
    }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className={clsx('TextCard border rounded', className)} data-attr="text-card" {...divProps} ref={ref}>
            <TextCardHeader
                textTile={textTile}
                dashboardId={dashboardId}
                showEditingControls={true}
                updateColor={updateColor}
                removeFromDashboard={removeFromDashboard}
            />
            <Textfit mode="multi" min={32} max={120}>
                <div className="whitespace-pre-wrap px-2 pb-2">{textTile.body}</div>
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
