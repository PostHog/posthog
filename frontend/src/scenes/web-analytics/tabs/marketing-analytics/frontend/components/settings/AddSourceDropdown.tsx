import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

interface AddSourceDropdownProps<T> {
    sources: T[]
    onSourceAdd: (source: T) => void
    buttonText?: string
}

export function AddSourceDropdown<T extends string>({
    sources,
    onSourceAdd,
    buttonText = 'Add new source',
}: AddSourceDropdownProps<T>): JSX.Element {
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
