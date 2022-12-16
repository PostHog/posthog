import { LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, autoCaptureEventToDescription } from 'lib/utils'
import { SharedListItemEvent } from '../../sharedListLogic'
import { SimpleKeyValueList } from './SimpleKeyValueList'

export interface ItemEventProps {
    item: SharedListItemEvent
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemEvent({ item, expanded, setExpanded }: ItemEventProps): JSX.Element {
    return (
        <div className={clsx('rounded bg-light border', expanded && 'border-primary')}>
            <div className="relative cursor-pointer" onClick={() => setExpanded(!expanded)}>
                <div className="flex gap-2 items-start p-2 text-xs cursor-pointer truncate">
                    <PropertyKeyInfo
                        className="font-medium"
                        disablePopover
                        ellipsis={true}
                        value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
                    />
                    {item.data.event === '$autocapture' ? <span className="text-muted-alt">(Autocapture)</span> : null}
                    {item.data.event === '$pageview' ? (
                        <span className="text-muted-alt">
                            {item.data.properties.$pathname || item.data.properties.$current_url}
                        </span>
                    ) : null}
                </div>
            </div>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <SimpleKeyValueList item={item.data.properties} />

                    <LemonDivider dashed />

                    <div className="flex gap-2 justify-end cursor-pointer" onClick={() => setExpanded(false)}>
                        <span className="text-muted-alt">Collapse</span>
                    </div>
                </div>
            )}
        </div>
    )
}
