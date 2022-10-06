import React from 'react'
import { Resizeable } from 'lib/components/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/InsightCard/handles'
import clsx from 'clsx'
import { DashboardTile, DashboardType, InsightColor, Tileable } from '~/types'
import { LemonButton, LemonButtonWithPopup, LemonDivider, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'
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
import { textCardModalLogic } from 'lib/components/TextCard/textCardModalLogic'

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
                        <Tabs>
                            <Tabs.TabPane tab="Write" key="write-card" destroyInactiveTabPane={true}>
                                <LemonTextArea
                                    data-attr="text-card-edit-area"
                                    autoFocus
                                    value={value}
                                    onChange={(newValue) => onChange(newValue)}
                                />
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
    dashboardId?: string | number
    textTile: DashboardTile
    children?: JSX.Element
    updateColor?: (newColor: Tileable['color']) => void
    removeFromDashboard?: () => void
}

function TextCardBody({ text }: { text: string }): JSX.Element {
    return (
        <div className={'w-full'}>
            <Textfit mode={text?.match(/([\r\n])/gm)?.length ? 'multi' : 'single'} min={16} max={60}>
                <div className="TextCard-Body whitespace-pre-wrap px-2 pb-2">
                    <ReactMarkdown>{text}</ReactMarkdown>
                </div>
            </Textfit>
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
    const { push } = useActions(router)
    const { text } = textTile
    if (!text) {
        throw new Error('TextCard requires text')
    }
    if (!dashboardId) {
        throw new Error('TextCard requires dashboardId')
    }
    return (
        <div
            className={clsx('TextCard border rounded flex flex-col overflow-hidden', className)}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            <div className={'flex flex-row px-2 pt-2'}>
                {textTile.color &&
                    textTile.color !==
                        InsightColor.White /* White has historically meant no color synonymously to null */ && (
                        <div className={clsx('InsightMeta__ribbon ml-2', textTile.color)} />
                    )}
                <UserActivityIndicator
                    className={'grow'}
                    at={text.last_modified_at}
                    by={text.created_by || text.last_modified_by}
                />
                <div className="min-h-4 flex items-center justify-end">
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    fullWidth
                                    onClick={() => push(urls.dashboardTextTile(dashboardId, textTile.id))}
                                    data-attr="edit-text"
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
                <TextCardBody text={text.body} />
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
