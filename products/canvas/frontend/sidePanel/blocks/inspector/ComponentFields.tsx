import type { BlockPropsRecord } from '../../../editing/blockLibrary/blockDefinitions'
import { ControlNote } from './ControlNote'
import { DraftInput } from './DraftInput'
import { EventPicker } from './EventPicker'
import { EventStepList } from './EventStepList'
import { InspectorField } from './InspectorField'
import { MATH_OPTIONS, MathValue, NUMBER_FORMATS } from './inspectorOptions'
import { InspectorSwitch } from './InspectorSwitch'
import { BlockPropsChange, asBoolean, asNumber, asString, asStrings } from './inspectorValues'
import { OptionSelect } from './OptionSelect'
import { PropertyPicker } from './PropertyPicker'
import { Segmented } from './Segmented'
import { SqlField } from './SqlField'
import { TitleField } from './TitleField'

function FollowFilters({ props, onChange }: { props: BlockPropsRecord; onChange: BlockPropsChange }): JSX.Element {
    return (
        <InspectorSwitch
            label="Use canvas filters"
            hint="When off, the date range still applies, but property filters do not."
            checked={asBoolean(props.followFilters, true)}
            onChange={(followFilters) => onChange({ ...props, followFilters: followFilters ? undefined : false })}
        />
    )
}

function MeasureField({
    label,
    props,
    onChange,
}: {
    label: string
    props: BlockPropsRecord
    onChange: BlockPropsChange
}): JSX.Element {
    return (
        <InspectorField label={label}>
            <div className="flex flex-col gap-2">
                <EventPicker
                    value={asString(props.event, '$pageview')}
                    onChange={(event) => onChange({ ...props, event })}
                />
                <OptionSelect
                    value={asString(props.math, 'total') as MathValue}
                    options={MATH_OPTIONS}
                    ariaLabel="Measure"
                    onChange={(math) => onChange({ ...props, math })}
                />
            </div>
        </InspectorField>
    )
}

/** The settings of a library block that does not declare its own param schema. */
export function ComponentFields({
    type,
    props,
    onChange,
}: {
    type: string
    props: BlockPropsRecord
    onChange: BlockPropsChange
}): JSX.Element {
    switch (type) {
        case 'Metric':
            return (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <MeasureField label="Measure" props={props} onChange={onChange} />
                    <InspectorField label="Number format">
                        <OptionSelect
                            value={asString(props.format, 'number')}
                            ariaLabel="Number format"
                            options={NUMBER_FORMATS}
                            onChange={(format) =>
                                onChange({ ...props, format: format === 'number' ? undefined : format })
                            }
                        />
                    </InspectorField>
                    <InspectorSwitch
                        label="Compare with previous period"
                        checked={asBoolean(props.compare, true)}
                        onChange={(compare) => onChange({ ...props, compare: compare ? undefined : false })}
                    />
                    <FollowFilters props={props} onChange={onChange} />
                </>
            )
        case 'Trend':
            return (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <InspectorField label="Chart">
                        <Segmented
                            value={asString(props.display, 'line')}
                            ariaLabel="Chart type"
                            options={[
                                { value: 'line', label: 'Line' },
                                { value: 'bar', label: 'Bar' },
                                { value: 'area', label: 'Area' },
                            ]}
                            onChange={(display) => onChange({ ...props, display })}
                        />
                    </InspectorField>
                    <EventStepList
                        label="Events"
                        itemLabel="event"
                        values={asStrings(props.events, ['$pageview'])}
                        min={1}
                        max={5}
                        onChange={(events) => onChange({ ...props, events })}
                    />
                    <InspectorField label="Measure">
                        <OptionSelect
                            value={asString(props.math, 'total') as MathValue}
                            options={MATH_OPTIONS}
                            ariaLabel="Measure"
                            onChange={(math) => onChange({ ...props, math })}
                        />
                    </InspectorField>
                    <InspectorField label="Break down by">
                        <PropertyPicker
                            value={asString(props.breakdown) || null}
                            allowNone
                            noneLabel="No breakdown"
                            onChange={(breakdown) => onChange({ ...props, breakdown: breakdown ?? undefined })}
                        />
                    </InspectorField>
                    <FollowFilters props={props} onChange={onChange} />
                </>
            )
        case 'TopList':
            return (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <InspectorField label="Rank values of">
                        <PropertyPicker
                            value={asString(props.breakdown, '$pathname')}
                            onChange={(breakdown) => {
                                if (breakdown) {
                                    onChange({ ...props, breakdown })
                                }
                            }}
                        />
                    </InspectorField>
                    <MeasureField label="By" props={props} onChange={onChange} />
                    <InspectorField label="Rows">
                        <Segmented
                            value={String(asNumber(props.limit, 8))}
                            ariaLabel="Rows"
                            options={[
                                { value: '5', label: '5' },
                                { value: '8', label: '8' },
                                { value: '12', label: '12' },
                            ]}
                            onChange={(limit) => onChange({ ...props, limit: Number(limit) })}
                        />
                    </InspectorField>
                    <FollowFilters props={props} onChange={onChange} />
                </>
            )
        case 'Funnel':
            return (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <EventStepList
                        label="Steps"
                        itemLabel="step"
                        values={asStrings(props.steps, ['$pageview', '$autocapture'])}
                        min={2}
                        max={8}
                        onChange={(steps) => onChange({ ...props, steps })}
                    />
                    <InspectorField label="Conversion window">
                        <Segmented
                            value={String(asNumber(props.windowDays, 14))}
                            ariaLabel="Conversion window"
                            options={[
                                { value: '1', label: '1 day' },
                                { value: '7', label: '7 days' },
                                { value: '14', label: '14 days' },
                                { value: '30', label: '30 days' },
                            ]}
                            onChange={(windowDays) => onChange({ ...props, windowDays: Number(windowDays) })}
                        />
                    </InspectorField>
                    <FollowFilters props={props} onChange={onChange} />
                </>
            )
        case 'SqlTable':
            return (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <SqlField
                        type="SqlTable"
                        sql={asString(props.query)}
                        onCommit={(query) => onChange({ ...props, query })}
                    />
                </>
            )
        case 'PropertyFilter':
            return (
                <>
                    <InspectorField label="Label">
                        <DraftInput
                            value={asString(props.label)}
                            ariaLabel="Label"
                            placeholder={asString(props.property, '$browser')}
                            onCommit={(label) => onChange({ ...props, label: label || undefined })}
                        />
                    </InspectorField>
                    <InspectorField
                        label="Property"
                        hint="Every data block that uses canvas filters shows only matching events."
                    >
                        <PropertyPicker
                            value={asString(props.property, '$browser')}
                            onChange={(property) => {
                                if (property) {
                                    onChange({ ...props, property })
                                }
                            }}
                        />
                    </InspectorField>
                </>
            )
        case 'DateRange':
            return (
                <ControlNote>
                    Sets the date range for every data block on this canvas. Each viewer can change it for themselves.
                </ControlNote>
            )
        case 'Interval':
            return <ControlNote>Groups every chart on this canvas by day, week or month.</ControlNote>
        default:
            return <ControlNote>This block has no settings here. Ask the agent to change it.</ControlNote>
    }
}
