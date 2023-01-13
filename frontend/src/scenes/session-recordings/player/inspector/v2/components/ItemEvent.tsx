import { LemonButton } from '@posthog/lemon-ui'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, autoCaptureEventToDescription } from 'lib/utils'
import { InspectorListItemEvent } from '../../playerInspectorLogic'
import { SimpleKeyValueList } from './SimpleKeyValueList'

export interface ItemEventProps {
    item: InspectorListItemEvent
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemEvent({ item, expanded, setExpanded }: ItemEventProps): JSX.Element {
    return (
        <div>
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} status={'primary-alt'} fullWidth>
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
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <SimpleKeyValueList item={item.data.properties} />
                </div>
            )}
        </div>
    )
}
