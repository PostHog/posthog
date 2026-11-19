import { z } from 'zod'

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Slider,
    Switch,
    Tabs,
    TabsList,
    TabsTrigger,
    Textarea,
    ToggleGroup,
    ToggleGroupItem,
    cn,
} from '@posthog/quill'

export function OptionsForm({
    schema,
    value,
    onChange,
}: {
    schema: z.ZodObject<any>
    value: Record<string, unknown>
    onChange: (v: Record<string, unknown>) => void
}): React.JSX.Element {
    const set = (k: string, v: unknown): void => onChange({ ...value, [k]: v })
    const groups = new Map<string, [string, z.ZodTypeAny][]>()
    for (const [key, t] of Object.entries(schema.shape as Record<string, z.ZodTypeAny>)) {
        const m = t.meta() ?? {}
        if (m.showIf && !m.showIf(value)) {
            continue
        }
        const g = m.group ?? 'Options'
        groups.set(g, [...(groups.get(g) ?? []), [key, t]])
    }
    return (
        <div className="flex flex-col gap-2">
            {[...groups].map(([g, fields]) => (
                <Section key={g} title={g}>
                    {fields.map(([key, t]) => (
                        <OptionField key={key} name={key} type={t} value={value[key]} onChange={(v) => set(key, v)} />
                    ))}
                </Section>
            ))}
        </div>
    )
}

function OptionField({
    name,
    type,
    value: v,
    onChange,
}: {
    name: string
    type: z.ZodTypeAny
    value: unknown
    onChange: (v: unknown) => void
}): React.JSX.Element {
    const m = type.meta() ?? {}
    const inner = unwrap(type)
    const title = m.title ?? humanize(name)
    const label = (o: string): string => m.labels?.[o] ?? humanize(o)
    const optional = type instanceof z.ZodOptional
    if (inner instanceof z.ZodBoolean) {
        return (
            <FieldRow label={title} description={m.description} inline>
                <Switch checked={!!v} onCheckedChange={(c: boolean) => onChange(c)} />
            </FieldRow>
        )
    }
    if (inner instanceof z.ZodEnum) {
        const opts = (inner as any).options as string[]
        const all = optional ? [OFF, ...opts] : opts
        const lbl = (o: string): string => (o === OFF ? 'Off' : label(o))
        const pick = (x: string): void => onChange(x === OFF ? undefined : x)
        if (all.length <= 4 && all.reduce((n, o) => n + lbl(o).length, 0) <= 30) {
            return (
                <FieldRow label={title} description={m.description}>
                    <Segmented options={all.map((o) => [o, lbl(o)])} value={String(v ?? OFF)} onChange={pick} />
                </FieldRow>
            )
        }
        return (
            <FieldRow label={title} description={m.description}>
                <OptionSelect
                    className="h-8 w-full text-xs"
                    options={all.map((o) => [o, lbl(o)] as const)}
                    value={String(v ?? OFF)}
                    onChange={pick}
                />
            </FieldRow>
        )
    }
    if (inner instanceof z.ZodArray && unwrap((inner as any).element) instanceof z.ZodEnum) {
        const opts = (unwrap((inner as any).element) as any).options as string[]
        const cur = Array.isArray(v) ? (v as string[]) : []
        return (
            <FieldRow label={title} description={m.description}>
                <ToggleGroup
                    multiple
                    variant="outline"
                    size="sm"
                    spacing={4}
                    className="dash-segmented flex-wrap"
                    value={cur}
                    onValueChange={(x: string[]) => onChange(x.length ? opts.filter((o) => x.includes(o)) : undefined)}
                >
                    {opts.map((o) => (
                        <ToggleGroupItem key={o} value={o} className="h-7 px-2 text-xs">
                            {label(o)}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </FieldRow>
        )
    }
    if (inner instanceof z.ZodArray) {
        return (
            <FieldRow label={title} description={m.description}>
                <Input
                    className="h-8 text-xs"
                    defaultValue={Array.isArray(v) ? v.join(', ') : ''}
                    key={Array.isArray(v) ? v.join(',') : ''}
                    onBlur={(e) => {
                        const list = e.target.value
                            .split(',')
                            .map((x) => x.trim())
                            .filter(Boolean)
                        onChange(list.length ? list : undefined)
                    }}
                />
            </FieldRow>
        )
    }
    if (inner instanceof z.ZodNumber && m.range) {
        const [min, max] = m.range
        return (
            <FieldRow label={title} description={m.description}>
                <div className="flex items-center gap-3">
                    <Slider
                        className={`flex-1 ${typeof v === 'number' ? '' : 'opacity-40'}`}
                        min={min}
                        max={max}
                        value={typeof v === 'number' ? v : max}
                        onValueChange={(x: number | readonly number[]) => onChange(Array.isArray(x) ? x[0] : x)}
                    />
                    <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                        {typeof v === 'number' ? v : 'auto'}
                    </span>
                    {optional && typeof v === 'number' && (
                        <button
                            type="button"
                            className="text-xs text-muted-foreground hover:text-foreground"
                            onClick={() => onChange(undefined)}
                        >
                            Reset
                        </button>
                    )}
                </div>
            </FieldRow>
        )
    }
    if (inner instanceof z.ZodNumber) {
        return (
            <FieldRow label={title} description={m.description}>
                <Input
                    type="number"
                    className="h-8 text-xs"
                    value={String(v ?? '')}
                    onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
                />
            </FieldRow>
        )
    }
    if (name === 'markdown') {
        return (
            <FieldRow label={title} description={m.description}>
                <Textarea
                    rows={10}
                    className="font-mono text-xs"
                    value={String(v ?? '')}
                    onChange={(e) => onChange(e.target.value)}
                />
            </FieldRow>
        )
    }
    return (
        <FieldRow label={title} description={m.description}>
            <Input
                className="h-8 text-xs"
                value={String(v ?? '')}
                onChange={(e) => onChange(e.target.value || undefined)}
            />
        </FieldRow>
    )
}

export function Section({
    title,
    children,
    defaultOpen = true,
    actions,
}: {
    title: string
    children: React.ReactNode
    defaultOpen?: boolean
    actions?: React.ReactNode
}): React.JSX.Element {
    return (
        <Collapsible defaultOpen={defaultOpen} className="dash-section rounded-lg border bg-card">
            <div className="flex items-center gap-2">
                <CollapsibleTrigger className="min-w-0 flex-1">{title}</CollapsibleTrigger>
                {actions}
            </div>
            <CollapsibleContent>
                <div className="flex flex-col gap-3 border-t px-3 py-3">{children}</div>
            </CollapsibleContent>
        </Collapsible>
    )
}

export function FieldRow({
    label,
    hint,
    description,
    inline,
    side,
    asLabel,
    children,
}: {
    label: string
    hint?: React.ReactNode
    description?: string
    inline?: boolean
    side?: boolean
    asLabel?: boolean
    children: React.ReactNode
}): React.JSX.Element {
    if (side) {
        return (
            <div className="flex items-start gap-2">
                <span className="w-16 shrink-0 pt-1.5 text-xs text-muted-foreground">{label}</span>
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{children}</div>
            </div>
        )
    }
    const head = (
        <div className="min-w-0">
            <div className="text-xs font-medium">
                {label}
                {hint && <span className="font-normal text-muted-foreground"> {hint}</span>}
            </div>
            {description && <div className="text-[11px] leading-snug text-muted-foreground">{description}</div>}
        </div>
    )
    if (inline) {
        return (
            <label className="flex items-center justify-between gap-3">
                {head}
                {children}
            </label>
        )
    }
    const Root = asLabel ? 'label' : 'div'
    return (
        <Root className="flex flex-col gap-1.5">
            {head}
            {children}
        </Root>
    )
}

export function Toggle({
    label,
    hint,
    checked,
    onChange,
}: {
    label: string
    hint?: string
    checked: boolean
    onChange: (v: boolean) => void
}): React.JSX.Element {
    return (
        <label className="flex items-start gap-2 text-xs">
            <Switch checked={checked} onCheckedChange={onChange} />
            <span className="flex flex-col">
                <span className="font-medium">{label}</span>
                {hint && <span className="text-muted-foreground">{hint}</span>}
            </span>
        </label>
    )
}

export function Segmented({
    options,
    value,
    onChange,
    className,
    disabled,
    'data-testid': testid,
}: {
    options: readonly (readonly [string, React.ReactNode, string?])[]
    value: string
    onChange: (v: string) => void
    className?: string
    disabled?: boolean
    'data-testid'?: string
}): React.JSX.Element {
    return (
        <Tabs value={value} onValueChange={(v: string) => onChange(v)}>
            <TabsList className={cn('h-7 w-full', className)} data-testid={testid}>
                {options.map(([o, l, id]) => (
                    <TabsTrigger
                        key={o}
                        value={o}
                        className="flex-1 cursor-pointer px-2 text-xs hover:bg-background/60 hover:text-foreground disabled:cursor-default"
                        disabled={disabled}
                        data-testid={id}
                    >
                        {l}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}

export function OptionSelect<T extends string>({
    options,
    value,
    onChange,
    className,
    disabled,
    'aria-label': ariaLabel,
    'data-testid': testid,
}: {
    options: readonly (readonly [T, React.ReactNode, ...unknown[]])[]
    value: string
    onChange: (v: T) => void
    className?: string
    disabled?: boolean
    'aria-label'?: string
    'data-testid'?: string
}): React.JSX.Element {
    return (
        <Select value={value} disabled={disabled} onValueChange={(v: any) => onChange(v)}>
            <SelectTrigger className={className} aria-label={ariaLabel} data-testid={testid}>
                <SelectValue>{(v: any) => options.find(([o]) => o === v)?.[1] ?? v}</SelectValue>
            </SelectTrigger>
            <SelectContent>
                {options.map(([o, l]) => (
                    <SelectItem key={o} value={o}>
                        {l}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

const OFF = '__off'
const humanize = (k: string): string =>
    k
        .replace(/_/g, ' ')
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/^./, (c) => c.toUpperCase())
        .replace(/ ([A-Z])/g, (_, c: string) => ` ${c.toLowerCase()}`)

function unwrap(t: z.ZodTypeAny): z.ZodTypeAny {
    let cur: any = t
    while (
        cur &&
        (cur instanceof z.ZodDefault ||
            cur instanceof z.ZodOptional ||
            cur instanceof z.ZodNullable ||
            cur instanceof z.ZodPipe)
    ) {
        cur = cur instanceof z.ZodPipe ? cur.def.out : (cur.def?.innerType ?? cur._def?.innerType ?? cur.unwrap?.())
    }
    return cur
}
