import { useActions } from 'kea'

import { PopoverTrigger } from '@posthog/quill'

import { TodaySpacesRow } from '~/layout/today/TodaySpacesRow'

import type { BetsEntryApi } from '../generated/api.schemas'
import { betsSidebarPreviewLogic } from '../logics/betsSidebarPreviewLogic'
import { BetsStatusGlyph } from './BetsStatusGlyph'

const OPEN_DELAY_MS = 400
const CLOSE_DELAY_MS = 100

interface BetsSidebarRowProps {
    bet: BetsEntryApi
    to: string
    active: boolean
}

export function BetsSidebarRow({ bet, to, active }: BetsSidebarRowProps): JSX.Element {
    const { suppressPreview, releasePreview } = useActions(betsSidebarPreviewLogic)
    return (
        <PopoverTrigger
            openOnHover
            delay={OPEN_DELAY_MS}
            closeDelay={CLOSE_DELAY_MS}
            payload={bet.id}
            nativeButton={false}
            render={<div className="min-w-0" />}
            onClick={(event) => {
                event.preventBaseUIHandler()
                suppressPreview()
            }}
            onPointerLeave={releasePreview}
        >
            <TodaySpacesRow
                label={bet.title}
                icon={<BetsStatusGlyph bet={bet} />}
                to={to}
                active={active}
                dataAttr="bets-sidebar-bet"
                optionValue={bet.id}
                ticker
            />
        </PopoverTrigger>
    )
}
