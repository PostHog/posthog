import { useMemo } from 'react'

import { getCustomCount } from '~/layout/panel-layout/ProjectTree/customIconRegistry'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneRow } from './TodayPaneRow'
import { productPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayProductIcon } from './TodayProductIcon'
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
    const Count = getCustomCount(product.type, product.href)
    return (
        <TodayPreviewTrigger payload={preview}>
            <TodayPaneRow
                value={value}
                label={label}
                icon={<TodayProductIcon item={product} />}
                badge={Count ? <Count /> : null}
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
