import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    Tabs,
    TabsList,
    TabsTrigger,
    cn,
} from '@posthog/quill'

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
