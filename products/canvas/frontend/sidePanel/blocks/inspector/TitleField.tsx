import type { BlockPropsRecord } from '../../../editing/blockLibrary/blockDefinitions'
import { DraftInput } from './DraftInput'
import { InspectorField } from './InspectorField'
import { BlockPropsChange, asString } from './inspectorValues'

/** A block's title. Empty falls back to the block's own default. */
export function TitleField({ props, onChange }: { props: BlockPropsRecord; onChange: BlockPropsChange }): JSX.Element {
    return (
        <InspectorField label="Title">
            <DraftInput
                value={asString(props.title)}
                ariaLabel="Title"
                placeholder="Leave empty for a default title"
                onCommit={(title) => onChange({ ...props, title: title || undefined })}
            />
        </InspectorField>
    )
}
