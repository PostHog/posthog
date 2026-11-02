import { useMemo } from 'react'

import { NavProductIcon } from '~/layout/panel-layout/navbar/tabs/NavProductIcon'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneRow } from './TodayPaneRow'
import { productPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayProductStarButton } from './TodayProductStarButton'

export interface TodayProductRowProps {
    value: string
    label: string
    product: FileSystemImport
    to: string
    active: boolean
    starred: boolean
    /** Every row in the Starred group has a star, so those rows show it only on hover. */
    inStarredGroup: boolean
}

export function TodayProductRow({
    value,
    label,
    product,
    to,
    active,
    starred,
    inStarredGroup,
}: TodayProductRowProps): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo(() => productPreview(label, product), [label, product])
    return (
        <TodayPreviewTrigger payload={preview}>
            <TodayPaneRow
                value={value}
                label={label}
                icon={<NavProductIcon item={product} />}
                to={to}
                active={active}
                action={<TodayProductStarButton product={product} starred={starred} />}
                // Like the current navigation, a starred row keeps its filled star in view.
                actionVisible={starred && !inStarredGroup}
                // pinned: tracking API, do not rename.
                dataAttr={inStarredGroup ? 'today-tool-starred' : 'today-tool'}
            />
        </TodayPreviewTrigger>
    )
}
