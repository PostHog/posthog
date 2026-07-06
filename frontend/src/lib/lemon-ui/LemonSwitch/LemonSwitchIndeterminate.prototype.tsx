/**
 * PROTOTYPE — throwaway code, do not use in production.
 *
 * Question: what should an indeterminate ("mixed") state look like on LemonSwitch?
 * Plan: three structurally different treatments, side by side in one Storybook story
 * ("Lemon UI/Lemon Switch/Indeterminate Prototype", run with `pnpm storybook`):
 *   A — Centered handle: the handle parks mid-track on a neutral track (position communicates).
 *   B — Dash in handle: track is filled like "checked", the handle carries a minus glyph
 *       (icon communicates, borrowed from indeterminate checkboxes).
 *   C — Half fill: the handle stretches over the left half while the track fades from
 *       gray to accent in a gradient (fill amount communicates, "literally half way").
 *   D — Full-width handle with dash: the handle stretches across the entire track and
 *       carries the minus glyph (icon communicates, no position to misread).
 *   E — Dash on track, no handle: the handle disappears entirely; a gray (border-colored)
 *       track shows a centered dash (most minimal, reads like a "blocked/mixed" badge).
 *   F — Same as E, but the track keeps the regular unchecked switch fill gray instead of
 *       the border gray.
 *   G — A + B + C combined: the handle parks mid-track (A), stretches to half the track
 *       width and sits on a gray-to-accent gradient track (C), carrying the minus glyph (B).
 *   H — Same as D, but the full-width handle is filled with the active accent blue and the
 *       dash is white.
 *   I — Same as A (centered handle on a neutral track), but the handle carries the minus
 *       glyph.
 *
 * Clicking an indeterminate switch resolves it to checked; after that it toggles normally.
 *
 * Verdict: TBD — once a variant wins, fold it into LemonSwitch proper and delete this file
 * and its stories file.
 */
import './LemonSwitch.scss'

import clsx from 'clsx'

export type PrototypeToggleValue = boolean | 'indeterminate'

export interface PrototypeSwitchProps {
    value: PrototypeToggleValue
    onChange: (nextChecked: boolean) => void
    label?: string | JSX.Element
    size?: 'small' | 'medium'
    bordered?: boolean
    fullWidth?: boolean
}

const CENTERED_TRANSLATE =
    'translateX(calc((var(--lemon-switch-width) - var(--lemon-switch-handle-width) - 2 * var(--lemon-switch-handle-gutter)) / 2))'

interface ShellProps extends PrototypeSwitchProps {
    trackStyle?: React.CSSProperties
    handleStyle?: React.CSSProperties
    handleContent?: JSX.Element
    trackContent?: JSX.Element
}

function SwitchShell({
    value,
    onChange,
    label,
    size = 'medium',
    bordered,
    fullWidth,
    trackStyle,
    handleStyle,
    handleContent,
    trackContent,
}: ShellProps): JSX.Element {
    const indeterminate = value === 'indeterminate'
    return (
        <div
            className={clsx('LemonSwitch', `LemonSwitch--${size}`, {
                'LemonSwitch--checked': value === true,
                'LemonSwitch--bordered': bordered,
                'LemonSwitch--full-width': fullWidth,
            })}
        >
            {label && <label>{label}</label>}
            <button
                type="button"
                role="switch"
                aria-checked={indeterminate ? 'mixed' : value === true}
                className="LemonSwitch__button"
                style={indeterminate ? trackStyle : undefined}
                onClick={() => onChange(value !== true)}
            >
                <div className="LemonSwitch__handle" style={indeterminate ? handleStyle : undefined}>
                    {indeterminate ? handleContent : null}
                </div>
                {indeterminate ? trackContent : null}
            </button>
        </div>
    )
}

/** A — handle parked mid-track, track stays neutral: position alone signals "mixed". */
export function VariantACenteredHandle(props: PrototypeSwitchProps): JSX.Element {
    return <SwitchShell {...props} handleStyle={{ transform: CENTERED_TRANSLATE }} />
}

/** I — like A, but the centered handle carries the minus glyph. */
export function VariantICenteredHandleDashNeutral(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            handleStyle={{ transform: CENTERED_TRANSLATE }}
            handleContent={<Dash color="var(--color-accent)" width="55%" />}
        />
    )
}

/** B — track filled like "checked", handle at the checked side carrying a minus glyph. */
export function VariantBDashInHandle(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{ backgroundColor: 'var(--color-accent)' }}
            handleStyle={{
                transform:
                    'translateX(calc(var(--lemon-switch-width) - var(--lemon-switch-handle-width) - 2 * var(--lemon-switch-handle-gutter)))',
            }}
            handleContent={<Dash color="var(--color-accent)" width="55%" />}
        />
    )
}

function Dash({ color, width }: { color: string; width: string }): JSX.Element {
    return (
        <span
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
            style={{
                width,
                height: '2px',
                borderRadius: '1px',
                backgroundColor: color,
            }}
        />
    )
}

/** C — handle stretches over the left half on a gray-to-accent gradient track: half on. */
export function VariantCHalfFill(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{
                background: 'linear-gradient(90deg, var(--color-bg-fill-switch), var(--color-accent))',
            }}
            handleStyle={{
                width: 'calc((var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter)) / 2)',
                transform: 'none',
            }}
        />
    )
}

/** D — handle stretches across the entire track and carries the minus glyph. */
export function VariantDFullWidthHandleDash(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{ backgroundColor: 'var(--color-accent)' }}
            handleStyle={{
                width: 'calc(var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter))',
                transform: 'none',
            }}
            handleContent={<Dash color="var(--color-accent)" width="35%" />}
        />
    )
}

/** H — like D, but the full-width handle is filled with the active accent blue and the dash is white. */
export function VariantHFullWidthHandleDashAccent(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{ backgroundColor: 'var(--color-accent)' }}
            handleStyle={{
                width: 'calc(var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter))',
                transform: 'none',
                backgroundColor: 'var(--color-accent)',
            }}
            handleContent={<Dash color="var(--color-bg-surface-primary)" width="35%" />}
        />
    )
}

/** E — no handle at all: a gray (border-colored) track shows a centered dash. */
export function VariantENoHandleDash(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{ backgroundColor: 'var(--color-border-primary)' }}
            handleStyle={{ visibility: 'hidden' }}
            trackContent={<Dash color="var(--color-bg-surface-primary)" width="35%" />}
        />
    )
}

/** F — like E, but the track keeps the regular unchecked switch fill gray. */
export function VariantFNoHandleDashFillGray(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{ backgroundColor: 'var(--color-bg-fill-switch)' }}
            handleStyle={{ visibility: 'hidden' }}
            trackContent={<Dash color="var(--color-bg-surface-primary)" width="35%" />}
        />
    )
}

/** G — A + B + C combined: centered half-width handle carrying the minus glyph on a gray-to-accent gradient track. */
export function VariantGCenteredHandleDash(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{
                background: 'linear-gradient(90deg, var(--color-bg-fill-switch), var(--color-accent))',
            }}
            handleStyle={{
                width: 'calc((var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter)) / 2)',
                transform: 'translateX(calc((var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter)) / 4))',
            }}
            handleContent={<Dash color="var(--color-accent)" width="40%" />}
        />
    )
}
