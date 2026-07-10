import { InspectorListItemExperimentVariant } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export interface ItemExperimentVariantProps {
    item: InspectorListItemExperimentVariant
}

export function ItemExperimentVariant({ item }: ItemExperimentVariantProps): JSX.Element {
    return (
        <div className="flex w-full items-start px-2 py-1 font-light font-mono text-xs">
            Saw variant "{item.data.variant}" — {item.data.experimentName}
        </div>
    )
}
