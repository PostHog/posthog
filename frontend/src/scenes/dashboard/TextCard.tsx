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
import ReactMarkdown from 'react-markdown'
import { IconMarkdown } from 'lib/components/icons'
import { Tabs } from 'antd'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

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
    const { submitTextTile, resetTextTile } = useActions(modalLogic)

    return (
        <LemonModal
            closable={true}
            isOpen={isOpen}
            title={''}
            onClose={() => {
                resetTextTile()
                onClose()
            }}
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
                        data-attr={textTileId === 'new' ? 'save-new-text-tile' : 'edit-text-tile-text'}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={dashboardTextTileModalLogic}
                props={{ dashboard: dashboard, textTileId: textTileId }}
                formKey={'textTile'}
                id="text-tile-form"
                className=""
                enableFormOnSubmit
            >
                <Field name="body" label="">
                    {({ value, onChange }) => (
                        <Tabs>
                            <Tabs.TabPane tab="Write" key="write-card">
                                <LemonTextArea autoFocus value={value} onChange={(newValue) => onChange(newValue)} />
                                <div className="text-muted inline-flex items-center space-x-1">
                                    <IconMarkdown />
                                    <span>Basic formatting and markdown support</span>
                                </div>
                            </Tabs.TabPane>
                            <Tabs.TabPane tab="Preview" key={'preview-card'}>
                                <TextCardBody text={value} />
                            </Tabs.TabPane>
                        </Tabs>
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

function TextCardBody({ text }: { text: string }): JSX.Element {
    return (
        <Textfit mode="multi" min={16} max={120}>
            <div className="whitespace-pre-wrap px-2 pb-2 TextCard-Body">
                <ReactMarkdown>{text}</ReactMarkdown>
            </div>
        </Textfit>
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
    const { push } = useActions(router)

    return (
        <div
            className={clsx('TextCard border rounded flex flex-col overflow-hidden', className)}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            <div className={'flex flex-row px-2'}>
                <UserActivityIndicator
                    className={'grow'}
                    at={textTile.last_modified_at}
                    by={textTile.created_by || textTile.last_modified_by}
                />
                <div className="min-h-4 flex items-center pt-2 px-2 justify-end">
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
                                                    active={availableColor === (textTile.color || InsightColor.White)}
                                                    status="stealth"
                                                    onClick={() => updateColor(availableColor)}
                                                    data-attr={`set-text-tile-ribbon-color-${availableColor}`}
                                                    icon={
                                                        availableColor !== InsightColor.White ? (
                                                            <Splotch color={availableColor as string as SplotchColor} />
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
                                    <LemonButton
                                        status="danger"
                                        onClick={removeFromDashboard}
                                        fullWidth
                                        data-attr="remove-text-tile-from-dashboard"
                                    >
                                        Remove from dashboard
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                </div>
            </div>
            <LemonDivider />
            <div className="flex p-2 pl-4">
                {textTile.color &&
                    textTile.color !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('DashboardCard__ribbon ml-2', textTile.color)} />
                    )}
                <TextCardBody text={textTile.body} />
            </div>
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
