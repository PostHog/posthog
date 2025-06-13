import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSource, ManualLinkSourceType } from '~/types'

interface AddSourceDropdownProps {
    sources: ExternalDataSource['source_type'][] | ManualLinkSourceType[]
    onSourceAdd: (source: any) => void // any because different files have different handler types
    buttonText?: string
}

export function AddSourceDropdown({
    sources,
    onSourceAdd,
    buttonText = 'Add new source',
}: AddSourceDropdownProps): JSX.Element {
    return (
        <LemonDropdown
            className="my-1"
            overlay={
                <div className="p-1">
                    {sources.map((source) => (
                        <LemonButton key={source} onClick={() => onSourceAdd(source)} fullWidth size="small">
                            <div className="flex items-center gap-2">
                                <DataWarehouseSourceIcon type={source} />
                                {source}
                                <IconPlus className="text-muted" />
                            </div>
                        </LemonButton>
                    ))}
                </div>
            }
        >
            <LemonButton type="primary" size="small">
                {buttonText}
            </LemonButton>
        </LemonDropdown>
    )
}
