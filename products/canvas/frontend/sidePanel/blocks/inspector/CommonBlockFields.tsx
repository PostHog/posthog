import { BlockPropsRecord, blockDefinition } from '../../../editing/blockLibrary/blockDefinitions'
import type { CanvasEditSelection } from '../../../editing/canvasSourceSnapshots'
import { DraftTextarea } from './DraftTextarea'
import { InspectorField } from './InspectorField'
import { WIDTHS } from './inspectorOptions'
import { BlockPropsChange, asString } from './inspectorValues'
import { Segmented } from './Segmented'

/** The description every data block takes, and the width of a block that sits in a grid. */
export function CommonBlockFields({
    selection,
    props,
    onChange,
}: {
    selection: CanvasEditSelection
    props: BlockPropsRecord
    onChange: BlockPropsChange
}): JSX.Element | null {
    const definition = selection.blockType ? blockDefinition(selection.blockType) : undefined
    if (!definition) {
        return null
    }
    const describable = definition.group === 'Data'
    const sizable = selection.layout.inGrid
    if (!describable && !sizable) {
        return null
    }
    return (
        <>
            {describable ? (
                <InspectorField label="Description">
                    <DraftTextarea
                        value={asString(props.description)}
                        ariaLabel="Description"
                        rows={2}
                        placeholder="What should readers take from this?"
                        onCommit={(description) =>
                            onChange({ ...props, description: description.trim() ? description : undefined })
                        }
                    />
                </InspectorField>
            ) : null}
            {sizable ? (
                <InspectorField label="Width">
                    <Segmented
                        value={asString(props.span, 'normal')}
                        ariaLabel="Width"
                        options={WIDTHS}
                        onChange={(span) => onChange({ ...props, span: span === 'normal' ? undefined : span })}
                    />
                </InspectorField>
            ) : null}
        </>
    )
}
