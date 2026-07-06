/**
 * PROTOTYPE — throwaway code, do not use in production.
 *
 * Question: what should an indeterminate ("mixed") state look like on LemonSwitch?
 * Plan: three structurally different treatments, side by side in one Storybook story
 * ("Lemon UI/Lemon Switch/Indeterminate Prototype", run with `pnpm storybook`):
 *   A — Centered handle: the handle parks mid-track on a neutral track (position communicates).
 *   B — Dash in handle: track is filled like "checked", the handle carries a minus glyph
 *       (icon communicates, borrowed from indeterminate checkboxes).
 *   C — Half fill: the handle stretches over the left half while the right half of the
 *       track shows accent color (fill amount communicates, "literally half way").
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
    label?: string
    size?: 'small' | 'medium'
}

const CENTERED_TRANSLATE =
    'translateX(calc((var(--lemon-switch-width) - var(--lemon-switch-handle-width) - 2 * var(--lemon-switch-handle-gutter)) / 2))'

interface ShellProps extends PrototypeSwitchProps {
    trackStyle?: React.CSSProperties
    handleStyle?: React.CSSProperties
    handleContent?: JSX.Element
}

function SwitchShell({
    value,
    onChange,
    label,
    size = 'medium',
    trackStyle,
    handleStyle,
    handleContent,
}: ShellProps): JSX.Element {
    const indeterminate = value === 'indeterminate'
    return (
        <div
            className={clsx('LemonSwitch', `LemonSwitch--${size}`, {
                'LemonSwitch--checked': value === true,
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
            </button>
        </div>
    )
}

/** A — handle parked mid-track, track stays neutral: position alone signals "mixed". */
export function VariantACenteredHandle(props: PrototypeSwitchProps): JSX.Element {
    return <SwitchShell {...props} handleStyle={{ transform: CENTERED_TRANSLATE }} />
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
            handleContent={
                <span
                    className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
                    style={{
                        width: '55%',
                        height: '2px',
                        borderRadius: '1px',
                        backgroundColor: 'var(--color-accent)',
                    }}
                />
            }
        />
    )
}

/** C — handle stretches over the left half, right half of the track shows accent: half on. */
export function VariantCHalfFill(props: PrototypeSwitchProps): JSX.Element {
    return (
        <SwitchShell
            {...props}
            trackStyle={{
                background: 'linear-gradient(90deg, var(--color-bg-fill-switch) 0 50%, var(--color-accent) 50% 100%)',
            }}
            handleStyle={{
                width: 'calc((var(--lemon-switch-width) - 2 * var(--lemon-switch-handle-gutter)) / 2)',
                transform: 'none',
            }}
        />
    )
}
