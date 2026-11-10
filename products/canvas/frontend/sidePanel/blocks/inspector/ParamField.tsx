import type { BlockPropValue } from '../../../editing/blockLibrary/blockDefinitions'
import type { ParamSpec } from '../../../editing/blockLibrary/params'
import { DraftInput } from './DraftInput'
import { DraftTextarea } from './DraftTextarea'
import { EventPicker } from './EventPicker'
import { EventStepList } from './EventStepList'
import { InsightPicker } from './InsightPicker'
import { InspectorField } from './InspectorField'
import { InspectorSwitch } from './InspectorSwitch'
import { asBoolean, asNumber, asString, asStrings } from './inspectorValues'
import { OptionSelect } from './OptionSelect'
import { ParamSlider } from './ParamSlider'
import { PropertyPicker } from './PropertyPicker'
import { Segmented } from './Segmented'

const SEGMENTED_OPTION_LIMIT = 4
const HEX_COLOR = /^#[0-9a-f]{6}$/i

function clampNumber(value: number, spec: ParamSpec): number {
    const low = spec.min ?? Number.NEGATIVE_INFINITY
    const high = spec.max ?? Number.POSITIVE_INFINITY
    return Math.min(high, Math.max(low, value))
}

/** One param a component declared with `editable()`, drawn as the control its kind calls for. */
export function ParamField({
    name,
    spec,
    value,
    onChange,
}: {
    name: string
    spec: ParamSpec
    value: unknown
    onChange: (value: BlockPropValue) => void
}): JSX.Element {
    const hint = spec.description ?? undefined
    switch (spec.kind) {
        case 'boolean':
            return (
                <InspectorSwitch label={spec.label} hint={hint} checked={asBoolean(value, false)} onChange={onChange} />
            )
        case 'longtext':
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <DraftTextarea value={asString(value)} ariaLabel={spec.label} rows={3} onCommit={onChange} />
                </InspectorField>
            )
        case 'number':
            if (spec.min !== null && spec.max !== null) {
                return (
                    <InspectorField label={spec.label} hint={hint}>
                        <ParamSlider value={asNumber(value, spec.min)} spec={spec} onCommit={onChange} />
                    </InspectorField>
                )
            }
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <DraftInput
                        value={String(asNumber(value, spec.min ?? 0))}
                        ariaLabel={spec.label}
                        onCommit={(next) => {
                            const parsed = Number(next)
                            if (Number.isFinite(parsed)) {
                                onChange(clampNumber(parsed, spec))
                            }
                        }}
                    />
                </InspectorField>
            )
        case 'select': {
            const current = asString(value, spec.options[0]?.value ?? '')
            return (
                <InspectorField label={spec.label} hint={hint}>
                    {spec.options.length <= SEGMENTED_OPTION_LIMIT ? (
                        <Segmented value={current} options={spec.options} ariaLabel={spec.label} onChange={onChange} />
                    ) : (
                        <OptionSelect
                            value={current}
                            options={spec.options}
                            ariaLabel={spec.label}
                            onChange={onChange}
                        />
                    )}
                </InspectorField>
            )
        }
        case 'event':
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <EventPicker value={asString(value, '$pageview')} onChange={onChange} />
                </InspectorField>
            )
        case 'events':
            return (
                <EventStepList
                    label={spec.label}
                    itemLabel="event"
                    values={asStrings(value, ['$pageview'])}
                    min={1}
                    max={8}
                    onChange={onChange}
                />
            )
        case 'property':
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <PropertyPicker value={asString(value) || null} onChange={(next) => onChange(next ?? undefined)} />
                </InspectorField>
            )
        case 'insight':
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <InsightPicker value={asString(value) || null} onChange={(next) => onChange(next ?? undefined)} />
                </InspectorField>
            )
        case 'color': {
            const color = asString(value, '#f54e00')
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <div className="flex items-center gap-2">
                        <label
                            className="relative size-8 shrink-0 cursor-pointer overflow-hidden rounded-md border border-border"
                            // The swatch shows the author's own color value, which no token can.
                            style={{ backgroundColor: color }}
                        >
                            <input
                                type="color"
                                aria-label={spec.label}
                                key={color}
                                defaultValue={HEX_COLOR.test(color) ? color : '#000000'}
                                onBlur={(event) => {
                                    if (event.target.value !== color) {
                                        onChange(event.target.value)
                                    }
                                }}
                                className="absolute inset-0 size-full cursor-pointer opacity-0"
                            />
                        </label>
                        <DraftInput value={color} ariaLabel={`${spec.label} hex`} onCommit={onChange} />
                    </div>
                </InspectorField>
            )
        }
        default:
            return (
                <InspectorField label={spec.label} hint={hint}>
                    <DraftInput value={asString(value)} ariaLabel={spec.label || name} onCommit={onChange} />
                </InspectorField>
            )
    }
}
