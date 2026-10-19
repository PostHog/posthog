import { useValues } from 'kea'
import { useMemo } from 'react'

import { cn } from '@posthog/quill'

import { NavProductIcon } from '~/layout/panel-layout/navbar/tabs/NavProductIcon'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { findProductShortcut } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneRow } from './TodayPaneRow'
import { productPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayProductStarButton } from './TodayProductStarButton'

export interface TodayProductRowProps {
    value: string
    label: string
    /** The product the row describes and stars. A Library row opens its product's list. */
    product: FileSystemImport
    to: string
    active: boolean
    icon?: JSX.Element | null
    /** Another control before the star, like the Library rows' create button. */
    extraAction?: JSX.Element | null
    /** Shows a starred row's filled star without a hover. The Starred group turns it off, as every row there has one. */
    pinStar?: boolean
    dataAttr: string
}

/** A Products pane row with the current navigation's product card on hover and a star button. */
export function TodayProductRow({
    value,
    label,
    product,
    to,
    active,
    icon,
    extraAction,
    pinStar = true,
    dataAttr,
}: TodayProductRowProps): JSX.Element {
    const { shortcutData } = useValues(projectTreeDataLogic)
    const starVisible = pinStar && !!findProductShortcut(product, shortcutData)
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo(() => productPreview(label, product), [label, product])
    return (
        <TodayPreviewTrigger payload={preview}>
            <TodayPaneRow
                value={value}
                label={label}
                icon={icon ?? <NavProductIcon item={product} />}
                to={to}
                active={active}
                action={
                    <span className="flex items-center">
                        {extraAction && (
                            <span
                                className={cn(
                                    'flex items-center',
                                    starVisible &&
                                        'opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100'
                                )}
                            >
                                {extraAction}
                            </span>
                        )}
                        <TodayProductStarButton product={product} />
                    </span>
                }
                // Like the current navigation, a starred row keeps its filled star in view.
                actionVisible={starVisible}
                actionCount={extraAction ? 2 : 1}
                dataAttr={dataAttr}
            />
        </TodayPreviewTrigger>
    )
}
