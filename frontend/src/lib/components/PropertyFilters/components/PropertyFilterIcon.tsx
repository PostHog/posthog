import { IconBuilding, IconCursorClick, IconPeople, IconPerson, IconPiggyBank } from '@posthog/icons'
import { Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { PropertyFilterType } from '~/types'

function propertyFilterIconInfo(type?: PropertyFilterType): { title: string; icon: JSX.Element } | null {
    switch (type) {
        case 'event':
            return { title: 'Event property', icon: <IconUnverifiedEvent /> }
        case 'person':
            return { title: 'Person property', icon: <IconPerson /> }
        case 'cohort':
            return { title: 'Cohort filter', icon: <IconPeople /> }
        case 'group':
            return { title: 'Group filter', icon: <IconBuilding /> }
        case 'behavioral':
            return { title: 'Performed event or action filter', icon: <IconCursorClick /> }
        case 'revenue_analytics':
            return { title: 'Revenue analytics filter', icon: <IconPiggyBank /> }
        default:
            return null
    }
}

export function PropertyFilterIcon({ type }: { type?: PropertyFilterType }): JSX.Element | null {
    const quillSurface = useQuillSurface()
    const info = propertyFilterIconInfo(type)

    if (!info) {
        return null
    }

    if (quillSurface) {
        return (
            <QuillTooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>{info.icon}</TooltipTrigger>
                <TooltipContent>{info.title}</TooltipContent>
            </QuillTooltip>
        )
    }

    return <Tooltip title={info.title}>{info.icon}</Tooltip>
}
