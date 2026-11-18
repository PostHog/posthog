import {
  CopySimple,
  Play,
  Plus,
  Sparkle,
  Trash,
  X,
} from "@phosphor-icons/react";
import {
  type BlockPropsRecord,
  type BlockPropValue,
  blockDefinition,
} from "@posthog/core/canvas/blockLibrary/blockDefinitions";
import {
  builderSql,
  SQL_BLOCK_TYPES,
  SQL_COLUMN_HINTS,
} from "@posthog/core/canvas/blockLibrary/blockSql";
import type {
  ParamSchema,
  ParamSpec,
} from "@posthog/core/canvas/blockLibrary/params";
import { Button, Slider } from "@posthog/quill";
import type { CanvasEditSelection } from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import {
  ControlNote,
  DraftInput,
  DraftTextarea,
  InspectorField,
  InspectorSwitch,
  MathSelect,
  type MathValue,
  OptionSelect,
  Segmented,
} from "@posthog/ui/features/canvas/blocks/inspector/fields";
import {
  EventPicker,
  InsightPicker,
  PropertyPicker,
} from "@posthog/ui/features/canvas/blocks/inspector/Pickers";
import { SqlEditor } from "@posthog/ui/features/canvas/components/context/SqlEditor";
import { type ReactNode, useEffect, useState } from "react";

type Change = (props: BlockPropsRecord) => void;

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStrings(value: unknown, fallback: string[]): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function cleanProps(props: Record<string, unknown>): BlockPropsRecord {
  const result: BlockPropsRecord = {};
  for (const [key, value] of Object.entries(props)) {
    if (key === "blockId") continue;
    result[key] = value as BlockPropValue;
  }
  return result;
}

function TitleField({
  props,
  onChange,
}: {
  props: BlockPropsRecord;
  onChange: Change;
}) {
  return (
    <InspectorField label="Title">
      <DraftInput
        value={asString(props.title)}
        ariaLabel="Title"
        placeholder="Leave empty for a default title"
        onCommit={(title) => onChange({ ...props, title: title || undefined })}
      />
    </InspectorField>
  );
}

function FollowFilters({
  props,
  onChange,
}: {
  props: BlockPropsRecord;
  onChange: Change;
}) {
  return (
    <InspectorSwitch
      label="Use canvas filters"
      hint="When off, the date range still applies, but property filters do not."
      checked={asBoolean(props.followFilters, true)}
      onChange={(followFilters) =>
        onChange({ ...props, followFilters: followFilters ? undefined : false })
      }
    />
  );
}

function StepList({
  label,
  values,
  min,
  max,
  onChange,
}: {
  label: string;
  values: string[];
  min: number;
  max: number;
  onChange: (values: string[]) => void;
}) {
  const seen = new Map<string, number>();
  return (
    <InspectorField label={label}>
      <div className="flex flex-col gap-1.5">
        {values.map((item, index) => {
          const count = seen.get(item) ?? 0;
          seen.set(item, count + 1);
          return (
            <div
              key={count ? `${item}#${count}` : item}
              className="flex items-center gap-1.5"
            >
              <span className="w-4 shrink-0 text-center text-[11px] text-muted-foreground tabular-nums">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <EventPicker
                  value={item}
                  onChange={(event) =>
                    onChange(
                      values.map((current, i) =>
                        i === index ? event : current,
                      ),
                    )
                  }
                />
              </div>
              <Button
                variant="default"
                size="icon-sm"
                aria-label="Remove"
                disabled={values.length <= min}
                onClick={() => onChange(values.filter((_, i) => i !== index))}
              >
                <X size={12} />
              </Button>
            </div>
          );
        })}
        {values.length < max ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => onChange([...values, "$pageview"])}
          >
            <Plus size={12} />
            Add
          </Button>
        ) : null}
      </div>
    </InspectorField>
  );
}

const NUMBER_FORMATS = [
  { value: "number", label: "Number" },
  { value: "percent", label: "Percent" },
  { value: "currency", label: "Currency" },
  { value: "duration", label: "Duration" },
];

const WIDTHS = [
  { value: "normal", label: "Normal" },
  { value: "wide", label: "Wide" },
  { value: "full", label: "Full" },
];

function CommonFields({
  selection,
  props,
  onChange,
}: {
  selection: CanvasEditSelection;
  props: BlockPropsRecord;
  onChange: Change;
}): ReactNode {
  const definition = selection.blockType
    ? blockDefinition(selection.blockType)
    : undefined;
  if (!definition) return null;
  const describable = definition.group === "Data";
  const sizable = selection.layout.inGrid;
  if (!describable && !sizable) return null;
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
              onChange({
                ...props,
                description: description.trim() ? description : undefined,
              })
            }
          />
        </InspectorField>
      ) : null}
      {sizable ? (
        <InspectorField label="Width">
          <Segmented
            value={asString(props.span, "normal")}
            ariaLabel="Width"
            options={WIDTHS}
            onChange={(span) =>
              onChange({
                ...props,
                span: span === "normal" ? undefined : span,
              })
            }
          />
        </InspectorField>
      ) : null}
    </>
  );
}

function MeasureField({
  label,
  props,
  onChange,
}: {
  label: string;
  props: BlockPropsRecord;
  onChange: Change;
}) {
  return (
    <InspectorField label={label}>
      <div className="flex flex-col gap-1.5">
        <EventPicker
          value={asString(props.event, "$pageview")}
          onChange={(event) => onChange({ ...props, event })}
        />
        <MathSelect
          value={asString(props.math, "total") as MathValue}
          onChange={(math) => onChange({ ...props, math })}
        />
      </div>
    </InspectorField>
  );
}

function ComponentFields({
  type,
  props,
  onChange,
}: {
  type: string;
  props: BlockPropsRecord;
  onChange: Change;
}): ReactNode {
  switch (type) {
    case "Metric":
      return (
        <>
          <TitleField props={props} onChange={onChange} />
          <MeasureField label="Measure" props={props} onChange={onChange} />
          <InspectorField label="Number format">
            <OptionSelect
              value={asString(props.format, "number")}
              ariaLabel="Number format"
              options={NUMBER_FORMATS}
              onChange={(format) =>
                onChange({
                  ...props,
                  format: format === "number" ? undefined : format,
                })
              }
            />
          </InspectorField>
          <InspectorSwitch
            label="Compare with previous period"
            checked={asBoolean(props.compare, true)}
            onChange={(compare) =>
              onChange({ ...props, compare: compare ? undefined : false })
            }
          />
          <FollowFilters props={props} onChange={onChange} />
        </>
      );
    case "Trend":
      return (
        <>
          <TitleField props={props} onChange={onChange} />
          <InspectorField label="Chart">
            <Segmented
              value={asString(props.display, "line") as "line" | "bar" | "area"}
              ariaLabel="Chart type"
              options={[
                { value: "line", label: "Line" },
                { value: "bar", label: "Bar" },
                { value: "area", label: "Area" },
              ]}
              onChange={(display) => onChange({ ...props, display })}
            />
          </InspectorField>
          <StepList
            label="Events"
            values={asStrings(props.events, ["$pageview"])}
            min={1}
            max={5}
            onChange={(events) => onChange({ ...props, events })}
          />
          <InspectorField label="Measure">
            <MathSelect
              value={asString(props.math, "total") as MathValue}
              onChange={(math) => onChange({ ...props, math })}
            />
          </InspectorField>
          <InspectorField label="Break down by">
            <PropertyPicker
              value={asString(props.breakdown) || null}
              allowNone
              noneLabel="No breakdown"
              onChange={(breakdown) =>
                onChange({ ...props, breakdown: breakdown ?? undefined })
              }
            />
          </InspectorField>
          <FollowFilters props={props} onChange={onChange} />
        </>
      );
    case "TopList":
      return (
        <>
          <TitleField props={props} onChange={onChange} />
          <InspectorField label="Rank values of">
            <PropertyPicker
              value={asString(props.breakdown, "$pathname")}
              onChange={(breakdown) => {
                if (breakdown) onChange({ ...props, breakdown });
              }}
            />
          </InspectorField>
          <MeasureField label="By" props={props} onChange={onChange} />
          <InspectorField label="Rows">
            <Segmented
              value={String(asNumber(props.limit, 8))}
              ariaLabel="Rows"
              options={[
                { value: "5", label: "5" },
                { value: "8", label: "8" },
                { value: "12", label: "12" },
              ]}
              onChange={(limit) => onChange({ ...props, limit: Number(limit) })}
            />
          </InspectorField>
          <FollowFilters props={props} onChange={onChange} />
        </>
      );
    case "Funnel":
      return (
        <>
          <TitleField props={props} onChange={onChange} />
          <StepList
            label="Steps"
            values={asStrings(props.steps, ["$pageview", "$autocapture"])}
            min={2}
            max={8}
            onChange={(steps) => onChange({ ...props, steps })}
          />
          <InspectorField label="Conversion window">
            <Segmented
              value={String(asNumber(props.windowDays, 14))}
              ariaLabel="Conversion window"
              options={[
                { value: "1", label: "1 day" },
                { value: "7", label: "7 days" },
                { value: "14", label: "14 days" },
                { value: "30", label: "30 days" },
              ]}
              onChange={(windowDays) =>
                onChange({ ...props, windowDays: Number(windowDays) })
              }
            />
          </InspectorField>
          <FollowFilters props={props} onChange={onChange} />
        </>
      );
    case "SqlTable":
      return (
        <>
          <TitleField props={props} onChange={onChange} />
          <SqlField
            type="SqlTable"
            sql={asString(props.query)}
            onCommit={(query) => onChange({ ...props, query })}
          />
        </>
      );
    case "PropertyFilter":
      return (
        <>
          <InspectorField label="Label">
            <DraftInput
              value={asString(props.label)}
              ariaLabel="Label"
              placeholder={asString(props.property, "$browser")}
              onCommit={(label) =>
                onChange({ ...props, label: label || undefined })
              }
            />
          </InspectorField>
          <InspectorField
            label="Property"
            hint="Every data block that uses canvas filters shows only matching events."
          >
            <PropertyPicker
              value={asString(props.property, "$browser")}
              onChange={(property) => {
                if (property) onChange({ ...props, property });
              }}
            />
          </InspectorField>
        </>
      );
    case "DateRange":
      return (
        <ControlNote>
          Sets the date range for every data block on this canvas. Each viewer
          can change it for themselves.
        </ControlNote>
      );
    case "Interval":
      return (
        <ControlNote>
          Groups every chart on this canvas by day, week or month.
        </ControlNote>
      );
    default:
      return (
        <ControlNote>
          This block has no settings here. Ask the agent to change it.
        </ControlNote>
      );
  }
}

const SEGMENTED_OPTION_LIMIT = 4;
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

function clampNumber(value: number, spec: ParamSpec): number {
  const low = spec.min ?? Number.NEGATIVE_INFINITY;
  const high = spec.max ?? Number.POSITIVE_INFINITY;
  return Math.min(high, Math.max(low, value));
}

function stepOf(spec: ParamSpec): number {
  if (spec.step !== null) return spec.step;
  const range = (spec.max ?? 1) - (spec.min ?? 0);
  return Number.isInteger(spec.min) && Number.isInteger(spec.max) && range >= 2
    ? 1
    : range / 100;
}

function firstValue(next: number | readonly number[]): number | undefined {
  return Array.isArray(next) ? next[0] : (next as number);
}

function ParamSlider({
  value,
  spec,
  onCommit,
}: {
  value: number;
  spec: ParamSpec;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const step = stepOf(spec);
  const decimals =
    step < 1 ? Math.min(2, String(step).split(".")[1]?.length ?? 1) : 0;
  return (
    <div className="flex items-center gap-3">
      <Slider
        aria-label={spec.label}
        value={[draft]}
        min={spec.min ?? 0}
        max={spec.max ?? 100}
        step={step}
        className="min-w-0 flex-1"
        onValueChange={(next: number | readonly number[]) => {
          const raw = firstValue(next);
          if (typeof raw === "number") setDraft(raw);
        }}
        onValueCommitted={(next: number | readonly number[]) => {
          const raw = firstValue(next);
          if (typeof raw === "number" && raw !== value)
            onCommit(Number(raw.toFixed(decimals)));
        }}
      />
      <span className="w-9 shrink-0 text-right text-muted-foreground text-xs tabular-nums">
        {draft.toFixed(decimals)}
      </span>
    </div>
  );
}

function ParamField({
  name,
  spec,
  value,
  onChange,
}: {
  name: string;
  spec: ParamSpec;
  value: unknown;
  onChange: (value: BlockPropValue) => void;
}): ReactNode {
  const hint = spec.description ?? undefined;
  switch (spec.kind) {
    case "boolean":
      return (
        <InspectorSwitch
          label={spec.label}
          hint={hint}
          checked={asBoolean(value, false)}
          onChange={onChange}
        />
      );
    case "longtext":
      return (
        <InspectorField label={spec.label} hint={hint}>
          <DraftTextarea
            value={asString(value)}
            ariaLabel={spec.label}
            rows={3}
            onCommit={onChange}
          />
        </InspectorField>
      );
    case "number":
      if (spec.min !== null && spec.max !== null) {
        return (
          <InspectorField label={spec.label} hint={hint}>
            <ParamSlider
              value={asNumber(value, spec.min)}
              spec={spec}
              onCommit={onChange}
            />
          </InspectorField>
        );
      }
      return (
        <InspectorField label={spec.label} hint={hint}>
          <DraftInput
            value={String(asNumber(value, spec.min ?? 0))}
            ariaLabel={spec.label}
            onCommit={(next) => {
              const parsed = Number(next);
              if (Number.isFinite(parsed)) onChange(clampNumber(parsed, spec));
            }}
          />
        </InspectorField>
      );
    case "select": {
      const current = asString(value, spec.options[0]?.value ?? "");
      return (
        <InspectorField label={spec.label} hint={hint}>
          {spec.options.length <= SEGMENTED_OPTION_LIMIT ? (
            <Segmented
              value={current}
              options={spec.options}
              ariaLabel={spec.label}
              onChange={onChange}
            />
          ) : (
            <OptionSelect
              value={current}
              options={spec.options}
              ariaLabel={spec.label}
              onChange={onChange}
            />
          )}
        </InspectorField>
      );
    }
    case "event":
      return (
        <InspectorField label={spec.label} hint={hint}>
          <EventPicker
            value={asString(value, "$pageview")}
            onChange={onChange}
          />
        </InspectorField>
      );
    case "events":
      return (
        <StepList
          label={spec.label}
          values={asStrings(value, ["$pageview"])}
          min={1}
          max={8}
          onChange={onChange}
        />
      );
    case "property":
      return (
        <InspectorField label={spec.label} hint={hint}>
          <PropertyPicker
            value={asString(value) || null}
            onChange={(next) => onChange(next ?? undefined)}
          />
        </InspectorField>
      );
    case "insight":
      return (
        <InspectorField label={spec.label} hint={hint}>
          <InsightPicker
            value={asString(value) || null}
            onChange={(next) => onChange(next ?? undefined)}
          />
        </InspectorField>
      );
    case "color": {
      const color = asString(value, "#f54e00");
      return (
        <InspectorField label={spec.label} hint={hint}>
          <div className="flex items-center gap-2">
            <label
              className="relative size-8 shrink-0 cursor-pointer overflow-hidden rounded-md border border-border"
              style={{ backgroundColor: color }}
            >
              <input
                type="color"
                aria-label={spec.label}
                value={HEX_COLOR.test(color) ? color : "#000000"}
                onChange={(event) => onChange(event.target.value)}
                className="absolute inset-0 size-full cursor-pointer opacity-0"
              />
            </label>
            <DraftInput
              value={color}
              ariaLabel={`${spec.label} hex`}
              onCommit={onChange}
            />
          </div>
        </InspectorField>
      );
    }
    default:
      return (
        <InspectorField label={spec.label} hint={hint}>
          <DraftInput
            value={asString(value)}
            ariaLabel={spec.label || name}
            onCommit={onChange}
          />
        </InspectorField>
      );
  }
}

function ParamsForm({
  schema,
  props,
  onChange,
}: {
  schema: ParamSchema;
  props: BlockPropsRecord;
  onChange: Change;
}) {
  return (
    <>
      {schema.map(({ name, spec }) => (
        <ParamField
          key={name}
          name={name}
          spec={spec}
          value={props[name] ?? spec.fallback}
          onChange={(value) => onChange({ ...props, [name]: value })}
        />
      ))}
    </>
  );
}

function BlockFields({
  selection,
  props,
  onChange,
}: {
  selection: CanvasEditSelection;
  props: BlockPropsRecord;
  onChange: Change;
}): ReactNode {
  if (selection.params) {
    return (
      <ParamsForm schema={selection.params} props={props} onChange={onChange} />
    );
  }
  if (!selection.blockType) return null;
  return (
    <ComponentFields
      type={selection.blockType}
      props={props}
      onChange={onChange}
    />
  );
}

function SqlField({
  type,
  sql,
  onCommit,
}: {
  type: string;
  sql: string;
  onCommit: (sql: string) => void;
}) {
  const [draft, setDraft] = useState(sql);
  useEffect(() => setDraft(sql), [sql]);
  const changed = draft.trim() !== sql.trim();
  return (
    <InspectorField
      label="HogQL"
      hint={
        <>
          {SQL_COLUMN_HINTS[type]} Keep{" "}
          <code className="font-mono">{"{filters}"}</code> in the WHERE clause
          so the canvas date range and filters apply.
        </>
      }
    >
      <div className="overflow-hidden rounded-md border border-border bg-card">
        <SqlEditor
          key={sql}
          initialValue={sql}
          onChange={setDraft}
          onRun={onCommit}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">⌘↵ to run</span>
        <Button
          variant="primary"
          size="sm"
          disabled={!changed}
          onClick={() => onCommit(draft)}
        >
          <Play size={12} weight="fill" />
          Run query
        </Button>
      </div>
    </InspectorField>
  );
}

function QueryModeFields({
  type,
  props,
  onChange,
  children,
}: {
  type: string;
  props: BlockPropsRecord;
  onChange: Change;
  children: ReactNode;
}) {
  const sql = typeof props.sql === "string" ? props.sql : null;
  return (
    <>
      <InspectorField label="Data">
        <Segmented
          value={sql === null ? "builder" : "sql"}
          ariaLabel="Data"
          options={[
            { value: "builder", label: "Builder" },
            { value: "sql", label: "SQL" },
          ]}
          onChange={(mode) =>
            onChange(
              mode === "sql"
                ? { ...props, sql: builderSql(type, props) }
                : { ...props, sql: undefined },
            )
          }
        />
      </InspectorField>
      {sql === null ? (
        children
      ) : (
        <>
          <TitleField props={props} onChange={onChange} />
          <SqlField
            type={type}
            sql={sql}
            onCommit={(next) => onChange({ ...props, sql: next })}
          />
        </>
      )}
    </>
  );
}

export function SourceInspector({
  selection,
  isRoot,
  onProps,
  onText,
  onDuplicate,
  onRemove,
}: {
  selection: CanvasEditSelection;
  isRoot: boolean;
  onProps: (props: BlockPropsRecord) => void;
  onText: (text: string) => void;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const props = cleanProps(selection.props);
  return (
    <div className="flex flex-col gap-4 p-3">
      {selection.params &&
      selection.blockType &&
      !blockDefinition(selection.blockType) ? (
        <div className="flex gap-2.5 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
          <Sparkle size={14} className="mt-0.5 shrink-0 text-accent-11" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-medium text-foreground text-xs">
              Set up by the agent
            </span>
            <span className="text-[11.5px] text-muted-foreground leading-snug">
              These fields come from the component's code, so you can change
              them without a prompt.
            </span>
          </div>
        </div>
      ) : null}
      {selection.blockType && SQL_BLOCK_TYPES.has(selection.blockType) ? (
        <QueryModeFields
          type={selection.blockType}
          props={props}
          onChange={onProps}
        >
          <BlockFields selection={selection} props={props} onChange={onProps} />
        </QueryModeFields>
      ) : (
        <BlockFields selection={selection} props={props} onChange={onProps} />
      )}
      <CommonFields selection={selection} props={props} onChange={onProps} />
      {!selection.blockType && selection.text !== null ? (
        <InspectorField label="Text">
          <DraftTextarea
            value={selection.text}
            ariaLabel="Text"
            rows={3}
            onCommit={onText}
          />
        </InspectorField>
      ) : null}
      {!selection.blockType && selection.text === null ? (
        <ControlNote>
          {isRoot
            ? "This is the whole canvas. Drag blocks into it from the panel."
            : "Move this element by dragging it on the canvas, or ask the agent to change it."}
        </ControlNote>
      ) : null}
      {isRoot ? null : (
        <div className="flex gap-1.5">
          <Button variant="outline" size="sm" onClick={onDuplicate}>
            <CopySimple size={12} />
            Duplicate
          </Button>
          <Button variant="outline" size="sm" onClick={onRemove}>
            <Trash size={12} />
            Delete
          </Button>
        </div>
      )}
    </div>
  );
}
