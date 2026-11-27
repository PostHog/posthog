import { IconEllipsis } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { CampaignMappingCellActions } from '../CampaignMapping/CampaignMappingCellActions'

export function QuillUtmAuditActionsMenu({ columnName, value }: { columnName: string; value: string }): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger render={<Button size="icon-sm" aria-label="Mapping actions" tooltip="Mapping actions" />}>
                <IconEllipsis />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto">
                <CampaignMappingCellActions columnName={columnName} value={value} />
            </PopoverContent>
        </Popover>
    )
}
