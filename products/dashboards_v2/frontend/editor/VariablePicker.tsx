import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'

import { IconCheck, IconChevronDown, IconGear, IconPlus, IconSearch, IconTelescope, IconX } from '@posthog/icons'
import { Button, Checkbox, Input, Popover, PopoverContent, PopoverTrigger, Spinner } from '@posthog/quill'

import { useDebounced } from '../lib/hooks'
import { useQuery } from '../lib/useQuery'

export const ALL = '$__all'

export type VariablePickerProps = {
    label: string
    options: string[]
    value: string[]
    multi?: boolean
    includeAll?: boolean
    loading?: boolean
    placeholder?: string
    popular?: Record<string, number>
    recent?: string[]
    labels?: Record<string, string>
    icons?: Record<string, ReactNode>
    icon?: ReactNode
    counts?: Record<string, number>
    details?: Record<string, string>
    values?: Record<string, string>
    creatable?: boolean
    clearable?: boolean
    prefix?: ReactNode
    total?: number
    onSearch?: (
        q: string
    ) => Promise<string[] | { options: string[]; labels?: Record<string, string>; details?: Record<string, string> }>
    onSettings?: () => void
    onBrowse?: (q: string) => void
    className?: string
    trigger?: ReactNode
    side?: 'bottom' | 'right'
    onChange: (next: string[]) => void
}

type Found = { options: string[]; labels?: Record<string, string>; details?: Record<string, string> }

export function VariablePicker({
    label,
    options: first,
    total,
    onSearch,
    multi,
    includeAll,
    loading,
    placeholder = 'None',
    popular,
    recent,
    labels,
    icons,
    icon,
    counts,
    details,
    values,
    creatable,
    clearable,
    prefix,
    onSettings,
    onBrowse,
    className,
    trigger,
    side,
    onChange,
    value: given,
}: VariablePickerProps): React.JSX.Element {
    icons = own(icons)
    counts = own(counts)
    details = own(details)
    values = own(values)
    popular = own(popular)
    const [open, setOpen] = useState(false)
    const [picked, setPicked] = useState<string[]>()
    const value = picked ?? given
    const set = (next: string[]): void => {
        setPicked(next)
        onChange(next)
    }
    const [q, setQ] = useState('')
    const inputRef = useRef<HTMLInputElement>(null)
    const capped = !!onSearch && (total ?? 0) > first.length
    const typed = useDebounced(q.trim(), 250)
    const id = useId()
    const found = useQuery<Found>({
        queryKey: ['variable-search', id, typed],
        enabled: capped && !!typed,
        queryFn: () =>
            onSearch!(typed)
                .then((r) => (Array.isArray(r) ? { options: r } : r))
                .catch(() => ({ options: first })),
    })
    const answered = capped && typed && found.data && typed === q.trim() ? found.data : undefined
    const options = answered?.options ?? first
    labels = own(answered?.labels ? { ...labels, ...answered.labels } : labels)
    values = own(answered?.details ? { ...values, ...answered.details } : values)
    const show = (o: string): string => labels?.[o] ?? o
    const searching = capped && !!q.trim() && (typed !== q.trim() || found.isFetching)
    const isAll = value.includes(ALL)
    const selected = useMemo(() => new Set(isAll ? options : value), [value, options, isAll])
    const all = useMemo(() => [...given.filter((v) => v !== ALL && !options.includes(v)), ...options], [given, options])
    const visible = useMemo(() => {
        const s = answered ? '' : q.trim().toLowerCase()
        return s
            ? all.filter(
                  (o) =>
                      o.toLowerCase().includes(s) ||
                      show(o).toLowerCase().includes(s) ||
                      details?.[o]?.toLowerCase().includes(s)
              )
            : all
    }, [all, q, labels, details, answered])
    const fresh = creatable && !multi && q.trim() && !all.includes(q.trim()) ? q.trim() : undefined
    const sections = useMemo(() => {
        const rec = (recent ?? []).filter((r) => visible.includes(r))
        const pop = visible.filter((o) => popular?.[o] && !rec.includes(o)).sort((a, b) => popular![b]! - popular![a]!)
        const rest = visible.filter((o) => !rec.includes(o) && !popular?.[o])
        return (
            rec.length || pop.length
                ? [
                      ['Recent', rec],
                      ['Used in dashboards', pop],
                      ['All', rest],
                  ]
                : [['', rest]]
        ) as [string, string[]][]
    }, [visible, popular, recent])
    useEffect(() => {
        setPicked(undefined)
        if (open) {
            setQ('')
            setTimeout(() => inputRef.current?.focus(), 30)
        }
    }, [open])

    const summary = given.includes(ALL)
        ? 'All'
        : given.length === 0
          ? loading
              ? 'Loading…'
              : placeholder
          : given.length <= 2
            ? given.map(show).join(', ')
            : `${given.length} selected`

    const toggle = (opt: string): void => {
        if (!multi) {
            onChange([opt])
            setOpen(false)
            return
        }
        if (isAll) {
            set(all.filter((o) => o !== opt))
            return
        }
        set(selected.has(opt) ? value.filter((v) => v !== opt) : [...value, opt])
    }
    const selectVisible = (): void => set([...new Set([...(isAll ? [] : value), ...visible])])
    const deselectVisible = (): void => {
        const vis = new Set(visible)
        set((isAll ? all : value).filter((v) => !vis.has(v)))
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            {trigger ? (
                <PopoverTrigger render={<button className={className} />}>{trigger}</PopoverTrigger>
            ) : (
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            className={`h-7 max-w-64 justify-between gap-1 font-normal ${className ?? ''}`}
                        />
                    }
                >
                    {prefix && (
                        <span
                            className="max-w-40 min-w-0 shrink truncate border-r pr-1.5 text-muted-foreground"
                            title={typeof prefix === 'string' ? prefix : undefined}
                        >
                            {prefix}
                        </span>
                    )}
                    <span className="flex min-w-0 flex-1 items-center gap-1.5 [&>svg]:size-3.5 [&>svg]:shrink-0 [&>svg]:opacity-70">
                        {(value.length === 1 && icons?.[value[0]!]) || icon}
                        <span className={`truncate ${loading ? 'opacity-60' : ''}`}>{summary}</span>
                    </span>
                    {loading ? (
                        <Spinner aria-label="Loading options" className="size-3.5 shrink-0" />
                    ) : (
                        <IconChevronDown className="size-3.5 shrink-0 opacity-60" />
                    )}
                </PopoverTrigger>
            )}
            <PopoverContent side={side} align="start" className="w-80 min-w-(--anchor-width) gap-0 p-0">
                <div className="border-b p-2">
                    <div className="relative">
                        {searching ? (
                            <Spinner
                                aria-label="Searching"
                                className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2"
                            />
                        ) : (
                            <IconSearch className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                        )}
                        <Input
                            ref={inputRef}
                            className="h-8 pl-7 pr-7 text-xs"
                            placeholder={`Search ${label.toLowerCase()}…`}
                            value={q}
                            onChange={(e) => setQ(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Escape') {
                                    setOpen(false)
                                }
                                if (e.key === 'Enter' && visible.length === 1 && !fresh) {
                                    toggle(visible[0]!)
                                } else if (e.key === 'Enter' && fresh) {
                                    toggle(fresh)
                                }
                                if (e.key === 'Enter' && multi && visible.length > 1 && q) {
                                    selectVisible()
                                }
                            }}
                        />
                        {q && (
                            <button
                                type="button"
                                aria-label="Clear search"
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                                onClick={() => setQ('')}
                            >
                                <IconX className="size-3.5" />
                            </button>
                        )}
                    </div>
                    {!multi && clearable && value.length > 0 && (
                        <Button
                            variant="outline"
                            size="xs"
                            className="mt-2"
                            onClick={() => {
                                onChange([])
                                setOpen(false)
                            }}
                        >
                            Clear: {placeholder}
                        </Button>
                    )}
                    {multi && (
                        <div className="mt-2 flex items-center gap-1 text-xs">
                            {includeAll && (
                                <Button
                                    variant={isAll ? 'primary' : 'outline'}
                                    size="xs"
                                    onClick={() => set(isAll ? [] : [ALL])}
                                    title="Match everything"
                                >
                                    All
                                </Button>
                            )}
                            <Button variant="outline" size="xs" onClick={selectVisible} disabled={!visible.length}>
                                Select {q ? 'matching' : 'all'}
                            </Button>
                            <Button
                                variant="outline"
                                size="xs"
                                onClick={deselectVisible}
                                disabled={!visible.some((o) => selected.has(o))}
                                title={`Empty selection shows: ${placeholder}`}
                            >
                                Deselect {q ? 'matching' : 'all'}
                            </Button>
                        </div>
                    )}
                </div>
                <div role="listbox" aria-multiselectable={multi} className="max-h-64 overflow-auto py-1">
                    {loading && !all.length && (
                        <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                            <Spinner className="size-3.5" />
                            Loading options…
                        </div>
                    )}
                    {searching && (
                        <div
                            className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground"
                            data-attr="dashboard-v2-picker-searching"
                        >
                            <Spinner className="size-3.5" />
                            Searching for “{q.trim()}”…
                        </div>
                    )}
                    {fresh && (
                        <button
                            type="button"
                            className="flex w-full items-center gap-2 px-3 py-1 text-left text-xs hover:bg-fill-hover"
                            onClick={() => toggle(fresh)}
                        >
                            <IconPlus className="size-3.5 shrink-0" />
                            <span className="truncate">
                                New: <b className="font-medium">{fresh}</b>
                            </span>
                            <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">Enter</span>
                        </button>
                    )}
                    {!loading && !searching && !visible.length && !fresh && (
                        <div className="px-3 py-2 text-xs text-muted-foreground">
                            {all.length ? 'No matches' : 'No options'}
                        </div>
                    )}
                    {sections.map(
                        ([title, opts]) =>
                            opts.length > 0 && (
                                <div key={title}>
                                    {title && (
                                        <div className="px-3 pb-0.5 pt-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                                            {title}
                                        </div>
                                    )}
                                    {opts.slice(0, 500).map((opt) => {
                                        const on = selected.has(opt)
                                        return (
                                            <button
                                                key={opt}
                                                type="button"
                                                role="option"
                                                aria-selected={on}
                                                className={`flex w-full items-center gap-2 px-3 py-1 text-left text-xs hover:bg-fill-hover ${on && !multi ? 'bg-fill-selected font-medium' : ''}`}
                                                onClick={() => toggle(opt)}
                                            >
                                                {multi && (
                                                    <Checkbox
                                                        checked={on}
                                                        className="pointer-events-none"
                                                        tabIndex={-1}
                                                    />
                                                )}
                                                {icons?.[opt] && (
                                                    <span className="shrink-0 text-muted-foreground [&>svg]:size-3.5">
                                                        {icons[opt]}
                                                    </span>
                                                )}
                                                <span className="flex min-w-0 flex-col">
                                                    <span
                                                        className={`truncate ${labels ? '' : 'font-mono'}`}
                                                        title={opt}
                                                    >
                                                        {show(opt)}
                                                    </span>
                                                    {details?.[opt] && (
                                                        <span
                                                            className="truncate text-[11px] font-normal text-muted-foreground"
                                                            title={details[opt]}
                                                        >
                                                            {details[opt]}
                                                        </span>
                                                    )}
                                                </span>
                                                <span className="ml-auto flex shrink-0 items-center gap-1.5">
                                                    {(popular?.[opt] ?? counts?.[opt]) ? (
                                                        <span
                                                            className="text-[10px] tabular-nums text-muted-foreground"
                                                            title={
                                                                popular?.[opt]
                                                                    ? `Used in ${popular[opt]} dashboards`
                                                                    : undefined
                                                            }
                                                        >
                                                            {popular?.[opt] ?? counts?.[opt]}
                                                        </span>
                                                    ) : null}
                                                    {values?.[opt] && (
                                                        <span className="text-[11px] tabular-nums text-muted-foreground">
                                                            {values[opt]}
                                                        </span>
                                                    )}
                                                    {!multi && on && <IconCheck className="size-3.5" />}
                                                </span>
                                            </button>
                                        )
                                    })}
                                </div>
                            )
                    )}
                </div>
                {(multi || onSettings || onBrowse || capped) && (
                    <div className="flex items-center gap-3 whitespace-nowrap border-t px-3 py-1 text-[11px] text-muted-foreground">
                        {multi && (
                            <span>
                                {isAll
                                    ? `All (${all.length})`
                                    : picked?.length === 0
                                      ? `None selected · closing keeps ${summary}`
                                      : `${value.length} of ${all.length} selected`}
                                {q ? ` · ${visible.length} shown` : ''}
                            </span>
                        )}
                        {capped && !q && (
                            <span className="truncate">
                                First {first.length}
                                {Number.isFinite(total) ? ` of ${total}` : ''}: type to search
                            </span>
                        )}
                        {multi && <span className="min-w-0 flex-1 truncate text-right">Enter selects matches</span>}
                        {onSettings && (
                            <Button
                                variant="default"
                                size="xs"
                                className="ml-auto -mr-2 text-[11px]"
                                title={`Edit the ${label} variable`}
                                onClick={() => {
                                    setOpen(false)
                                    onSettings()
                                }}
                            >
                                <IconGear className="size-3" /> Edit variable
                            </Button>
                        )}
                        {onBrowse && (
                            <Button
                                variant="default"
                                size="xs"
                                className="ml-auto -mr-2 text-[11px]"
                                title="See every one, with what it carries and how often"
                                data-attr="dashboard-v2-picker-browse"
                                onClick={() => {
                                    setOpen(false)
                                    onBrowse(q)
                                }}
                            >
                                <IconTelescope className="size-3" /> Browse all…
                            </Button>
                        )}
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}

const own = <T,>(r?: Record<string, T>): Record<string, T> | undefined => r && Object.assign(Object.create(null), r)
