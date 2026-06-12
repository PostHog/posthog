import './PaperDesk.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { type ButtonHTMLAttributes, forwardRef, type InputHTMLAttributes, type ReactNode, useState } from 'react'

import { CLOUD_HOSTNAMES, SSO_PROVIDER_NAMES } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region, SSOProvider } from '~/types'

/* ---------- icons (ported from the design) ---------- */

export function GoogleIcon(): JSX.Element {
    return (
        <svg viewBox="0 0 48 48" width="17" height="17" aria-hidden>
            <path
                fill="#FFC107"
                d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22 22-9.8 22-22c0-1.5-.2-2.6-.4-3.5z"
            />
            <path
                fill="#FF3D00"
                d="M5.3 13.7l6.6 4.8C13.7 14.6 18.5 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 4.1 29.6 2 24 2 16.3 2 9.7 6.3 5.3 13.7z"
            />
            <path
                fill="#4CAF50"
                d="M24 46c5.5 0 10.4-2.1 14.1-5.5l-6.5-5.5C29.6 36.5 26.9 37.5 24 37.5c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.6 41.6 16.2 46 24 46z"
            />
            <path
                fill="#1976D2"
                d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4.1 5.6l6.5 5.5C39.9 36.8 44 31.2 44 24c0-1.5-.2-2.6-.4-3.5z"
            />
        </svg>
    )
}

export function GithubIcon({ color = '#181717' }: { color?: string }): JSX.Element {
    return (
        <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden>
            <path
                fill={color}
                d="M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.2.8-.5v-2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.3-1.3-1.7-1.3-1.7-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2 1-.3 2-.4 3-.4s2 .1 3 .4c2.3-1.5 3.3-1.2 3.3-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.6.8.5 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z"
            />
        </svg>
    )
}

export function GitlabIcon(): JSX.Element {
    return (
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
            <path fill="#E24329" d="m12 21.42 3.684-11.333H8.316L12 21.42Z" />
            <path fill="#FC6D26" d="M12 21.42 8.316 10.087H3.155L12 21.42Z" />
            <path fill="#FCA326" d="M3.155 10.087.96 16.84a.748.748 0 0 0 .272.836L12 21.42 3.155 10.087Z" />
            <path fill="#E24329" d="M3.155 10.087h5.16L6.097 3.262a.385.385 0 0 0-.732 0L3.155 10.087Z" />
            <path fill="#FC6D26" d="m12 21.42 3.684-11.333h5.161L12 21.42Z" />
            <path fill="#FCA326" d="m20.845 10.087 2.195 6.753a.748.748 0 0 1-.272.836L12 21.42l8.845-11.333Z" />
            <path fill="#E24329" d="M20.845 10.087h-5.16l2.218-6.825a.385.385 0 0 1 .732 0l2.21 6.825Z" />
        </svg>
    )
}

export function KeyIcon({ size = 16 }: { size?: number }): JSX.Element {
    return (
        <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            width={size}
            height={size}
            aria-hidden
        >
            <path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z" />
            <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />
        </svg>
    )
}

function LockIcon(): JSX.Element {
    return (
        <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            width="14"
            height="14"
            aria-hidden
        >
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
    )
}

function providerIcon(provider: string): JSX.Element {
    if (provider.includes('google')) {
        return <GoogleIcon />
    }
    if (provider.includes('github')) {
        return <GithubIcon />
    }
    if (provider.includes('gitlab')) {
        return <GitlabIcon />
    }
    return <KeyIcon size={20} />
}

/* ---------- card title ---------- */

export function PaperCardTitle({
    title,
    sub,
    className,
}: {
    title: ReactNode
    sub?: ReactNode
    className?: string
}): JSX.Element {
    return (
        <div className={className ?? 'mb-6'}>
            <h1 className="PaperDesk__title">{title}</h1>
            {sub && <p className="PaperDesk__sub">{sub}</p>}
        </div>
    )
}

/* ---------- field ---------- */

export function PaperField({
    label,
    right,
    help,
    helpError,
    className,
    children,
}: {
    label?: ReactNode
    right?: ReactNode
    help?: ReactNode
    helpError?: boolean
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className={clsx('PaperDesk__field', className)}>
            {(label || right) && (
                <div className="PaperDesk__field-labelRow">
                    {label ? <label className="PaperDesk__field-label">{label}</label> : <span />}
                    {right}
                </div>
            )}
            {children}
            {help && (
                <p className={clsx('PaperDesk__field-help', helpError && 'PaperDesk__field-help--error')}>{help}</p>
            )}
        </div>
    )
}

export const PaperInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
    function PaperInput({ invalid, className, ...props }, ref): JSX.Element {
        return (
            <input
                ref={ref}
                className={clsx('PaperDesk__input', invalid && 'PaperDesk__input--invalid', className)}
                {...props}
            />
        )
    }
)

export function PaperLockedEmail({ email }: { email: string }): JSX.Element {
    return (
        <span className="PaperDesk__lockedWrap">
            <input type="email" value={email} disabled readOnly className="PaperDesk__input PaperDesk__input--locked" />
            <LockIcon />
        </span>
    )
}

/* ---------- buttons ---------- */

interface PrimaryButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
    loading?: boolean
    loadingLabel?: string
    icon?: ReactNode
    htmlType?: 'submit' | 'button'
}

export function PaperPrimaryButton({
    loading,
    loadingLabel = 'One sec…',
    icon,
    htmlType = 'submit',
    children,
    className,
    disabled,
    ...props
}: PrimaryButtonProps): JSX.Element {
    return (
        <button
            type={htmlType}
            className={clsx('PaperDesk__primaryBtn', className)}
            disabled={disabled || loading}
            {...props}
        >
            {loading ? (
                <>
                    <span className="PaperDesk__spinner" aria-hidden /> {loadingLabel}
                </>
            ) : (
                <>
                    {icon}
                    {children}
                </>
            )}
        </button>
    )
}

export function PaperSecondaryButton({
    icon,
    children,
    className,
    ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode }): JSX.Element {
    return (
        <button type="button" className={clsx('PaperDesk__secondaryBtn', className)} {...props}>
            {icon}
            {children}
        </button>
    )
}

/* ---------- misc primitives ---------- */

export function PaperDivider({ label, dashed }: { label?: ReactNode; dashed?: boolean }): JSX.Element {
    if (dashed) {
        return (
            <>
                <hr className="PaperDesk__dashed-divider" />
                {label && <p className="PaperDesk__divider-caption">{label}</p>}
            </>
        )
    }
    return (
        <div className="PaperDesk__divider my-4">
            <span className="PaperDesk__divider-line" />
            {label && <span className="PaperDesk__divider-label">{label}</span>}
            <span className="PaperDesk__divider-line" />
        </div>
    )
}

export function PaperFooterNote({ children }: { children: ReactNode }): JSX.Element {
    return <p className="PaperDesk__footer">{children}</p>
}

interface PaperLinkProps {
    to?: string
    onClick?: () => void
    target?: string
    tabIndex?: number
    muted?: boolean
    className?: string
    children: ReactNode
}

export function PaperLink({ to, onClick, target, tabIndex, muted, className, children }: PaperLinkProps): JSX.Element {
    return (
        <Link
            to={to}
            onClick={onClick}
            target={target}
            tabIndex={tabIndex}
            className={clsx('PaperDesk__link', muted && 'PaperDesk__link--muted', className)}
        >
            {children}
        </Link>
    )
}

/* ---------- password strength (3-segment meter, design scoring) ---------- */

const STRENGTH_LABELS = ['min. 8 characters', 'too weak', 'okay', 'strong']

function passwordScore(pw: string): number {
    if (!pw) {
        return 0
    }
    if (pw.length < 8) {
        return 1
    }
    const hasUpperOrSymbol = /[A-Z]/.test(pw) || /[^a-zA-Z0-9]/.test(pw)
    const hasDigit = /\d/.test(pw)
    if (hasUpperOrSymbol && hasDigit && pw.length >= 12) {
        return 3
    }
    if (hasDigit || /[^a-zA-Z0-9]/.test(pw) || pw.length >= 12) {
        return 2
    }
    return 1
}

export function PaperPasswordStrength({ password }: { password: string }): JSX.Element {
    const score = passwordScore(password)
    return (
        <span className={clsx('PaperDesk__strength', score > 0 && `PaperDesk__strength--${score}`)}>
            <span>{STRENGTH_LABELS[score]}</span>
            <span className="PaperDesk__strength-segments">
                {[1, 2, 3].map((i) => (
                    <span
                        key={i}
                        className={clsx('PaperDesk__strength-seg', i <= score && 'PaperDesk__strength-seg--on')}
                    />
                ))}
            </span>
        </span>
    )
}

/* ---------- org plaque ---------- */

export function OrgTile({ name }: { name: string }): JSX.Element {
    return (
        <div className="PaperDesk__orgTile" aria-hidden>
            {(name || '?').trim().charAt(0).toUpperCase()}
        </div>
    )
}

/* ---------- segmented data-region toggle (navigates cloud host) ---------- */

/* ---------- regional flags (crafted SVG — flag emoji don't render on Windows) ---------- */

function FiveStar({ cx, cy, r, fill }: { cx: number; cy: number; r: number; fill: string }): JSX.Element {
    const pts: string[] = []
    for (let i = 0; i < 5; i++) {
        const outer = ((-90 + i * 72) * Math.PI) / 180
        const inner = ((-90 + i * 72 + 36) * Math.PI) / 180
        pts.push(`${cx + r * Math.cos(outer)},${cy + r * Math.sin(outer)}`)
        pts.push(`${cx + r * 0.382 * Math.cos(inner)},${cy + r * 0.382 * Math.sin(inner)}`)
    }
    return <polygon points={pts.join(' ')} fill={fill} />
}

function USFlag(): JSX.Element {
    return (
        <svg viewBox="0 0 150 96" width={18} aria-hidden>
            {Array.from({ length: 13 }, (_, i) => (
                <rect key={i} y={(i * 96) / 13} width="150" height={96 / 13} fill={i % 2 ? '#fff' : '#B22234'} />
            ))}
            <rect width="66" height={(96 / 13) * 7} fill="#3C3B6E" />
            {Array.from({ length: 7 }, (_, row) =>
                Array.from({ length: row % 2 ? 5 : 6 }, (_, col) => (
                    <FiveStar
                        key={`${row}-${col}`}
                        cx={7 + col * 11 + (row % 2 ? 5.5 : 0)}
                        cy={6 + row * 6.2}
                        r={2.6}
                        fill="#fff"
                    />
                ))
            )}
        </svg>
    )
}

function EUFlag(): JSX.Element {
    return (
        <svg viewBox="0 0 150 96" width={18} aria-hidden>
            <rect width="150" height="96" fill="#003399" />
            {Array.from({ length: 12 }, (_, i) => {
                const a = ((-90 + i * 30) * Math.PI) / 180
                return <FiveStar key={i} cx={75 + 26 * Math.cos(a)} cy={48 + 26 * Math.sin(a)} r={5.5} fill="#FFCC00" />
            })}
        </svg>
    )
}

function MiniFlag({ region }: { region: Region }): JSX.Element {
    return <span className="PaperDesk__flag">{region === Region.EU ? <EUFlag /> : <USFlag />}</span>
}

const REGIONS: { value: Region; label: string }[] = [
    { value: Region.US, label: 'United States' },
    { value: Region.EU, label: 'European Union' },
]

export function PaperRegionField(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    // Off-Cloud (dev preview) the toggle is purely visual; on Cloud the active region comes from preflight.
    const [devRegion, setDevRegion] = useState<Region>(Region.US)

    // The US/EU choice only applies to PostHog Cloud. We also render it in local dev (is_debug) so the
    // design can be previewed; on genuine self-hosted it stays hidden (there is no US/EU choice there).
    if (!preflight?.cloud && !preflight?.is_debug) {
        return null
    }

    const activeRegion = preflight?.cloud ? (preflight.region ?? Region.US) : devRegion

    const selectRegion = (region: Region): void => {
        if (region === activeRegion) {
            return
        }
        if (preflight?.cloud) {
            const { pathname, search, hash } = router.values.currentLocation
            window.location.href = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
            return
        }
        setDevRegion(region)
    }

    return (
        <div className="PaperDesk__region">
            <label className="PaperDesk__field-label">Data region</label>
            <div role="radiogroup" className="PaperDesk__region-track">
                {REGIONS.map((region) => {
                    const on = activeRegion === region.value
                    return (
                        <button
                            key={region.value}
                            type="button"
                            role="radio"
                            aria-checked={on}
                            className={clsx('PaperDesk__region-option', on && 'PaperDesk__region-option--active')}
                            onClick={() => selectRegion(region.value)}
                        >
                            <MiniFlag region={region.value} />
                            <span className="PaperDesk__region-option-label">{region.label}</span>
                        </button>
                    )
                })}
            </div>
        </div>
    )
}

/* ---------- icon social row (real OAuth links + optional passkey) ---------- */

export function PaperSocialIcons({
    verb = 'Log in',
    lastUsed,
    caption,
    showPasskey,
    onPasskey,
    extraQueryParams,
}: {
    verb?: string
    lastUsed?: string | null
    caption?: ReactNode
    showPasskey?: boolean
    onPasskey?: () => void
    extraQueryParams?: Record<string, string>
}): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { searchParams } = useValues(router)

    const available = (preflight?.available_social_auth_providers ?? {}) as Record<string, boolean>
    const order = Object.keys(SSO_PROVIDER_NAMES)
    const providers = Object.keys(available)
        .filter((p) => available[p])
        .sort((a, b) => order.indexOf(a) - order.indexOf(b))

    if (providers.length === 0 && !showPasskey) {
        return null
    }

    const urlFor = (provider: string): string => {
        const params: Record<string, string> = { ...extraQueryParams }
        if (searchParams.next) {
            params.next = searchParams.next
        }
        if (provider === 'saml') {
            params.idp = 'posthog_custom'
        }
        return combineUrl(`/login/${provider}/`, params).url
    }

    return (
        <div>
            <div className="PaperDesk__social">
                {providers.map((provider) => (
                    <Link
                        key={provider}
                        to={urlFor(provider)}
                        disableClientSideRouting
                        className="PaperDesk__social-btn"
                        title={`${verb} with ${SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider}`}
                        aria-label={`${verb} with ${SSO_PROVIDER_NAMES[provider as SSOProvider] ?? provider}`}
                    >
                        {providerIcon(provider)}
                        {lastUsed === provider && <span className="PaperDesk__social-badge">Last used</span>}
                    </Link>
                ))}
                {showPasskey && (
                    <button
                        type="button"
                        className="PaperDesk__social-btn"
                        onClick={onPasskey}
                        title={`${verb} with a passkey`}
                        aria-label={`${verb} with a passkey`}
                    >
                        <span className="PaperDesk__sso-icon">
                            <KeyIcon size={22} />
                        </span>
                    </button>
                )}
            </div>
            {caption && <p className="PaperDesk__social-caption">{caption}</p>}
        </div>
    )
}
