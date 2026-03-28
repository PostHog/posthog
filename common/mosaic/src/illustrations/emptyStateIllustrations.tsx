import type { ReactElement } from 'react'

export type EmptyStateIllustrationType = 'table' | 'chart' | 'funnel' | 'number' | 'generic'

const COLOR = 'var(--color-text-secondary, #6b7280)'
const FAINT = 'var(--color-border-primary, #e5e7eb)'

export function emptyStateIllustration(type: EmptyStateIllustrationType): ReactElement {
    switch (type) {
        case 'table':
            return (
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="8" y="10" width="32" height="28" rx="3" stroke={FAINT} strokeWidth="1.5" fill="none" />
                    <line x1="8" y1="18" x2="40" y2="18" stroke={FAINT} strokeWidth="1.5" />
                    <line x1="8" y1="26" x2="40" y2="26" stroke={FAINT} strokeWidth="1.5" />
                    <line x1="8" y1="34" x2="40" y2="34" stroke={FAINT} strokeWidth="1.5" />
                    <line x1="20" y1="10" x2="20" y2="38" stroke={FAINT} strokeWidth="1.5" />
                    <rect x="9" y="11" width="30" height="6" rx="1" fill={FAINT} opacity="0.4" />
                    <line
                        x1="12"
                        y1="22"
                        x2="17"
                        y2="22"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                    <line
                        x1="24"
                        y1="22"
                        x2="32"
                        y2="22"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                    <line
                        x1="12"
                        y1="30"
                        x2="17"
                        y2="30"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                    <line
                        x1="24"
                        y1="30"
                        x2="36"
                        y2="30"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                </svg>
            )
        case 'chart':
            return (
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <line x1="10" y1="38" x2="40" y2="38" stroke={FAINT} strokeWidth="1.5" strokeLinecap="round" />
                    <line x1="10" y1="10" x2="10" y2="38" stroke={FAINT} strokeWidth="1.5" strokeLinecap="round" />
                    <line
                        x1="14"
                        y1="30"
                        x2="36"
                        y2="30"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeDasharray="4 3"
                        opacity="0.4"
                    />
                    <line
                        x1="10"
                        y1="18"
                        x2="40"
                        y2="18"
                        stroke={FAINT}
                        strokeWidth="1"
                        strokeDasharray="3 3"
                        opacity="0.5"
                    />
                    <line
                        x1="10"
                        y1="26"
                        x2="40"
                        y2="26"
                        stroke={FAINT}
                        strokeWidth="1"
                        strokeDasharray="3 3"
                        opacity="0.5"
                    />
                </svg>
            )
        case 'funnel':
            return (
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="8" y="12" width="32" height="6" rx="2" fill={FAINT} opacity="0.5" />
                    <rect x="12" y="22" width="24" height="6" rx="2" fill={FAINT} opacity="0.35" />
                    <rect x="16" y="32" width="16" height="6" rx="2" fill={FAINT} opacity="0.2" />
                </svg>
            )
        case 'number':
            return (
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <line
                        x1="14"
                        y1="24"
                        x2="34"
                        y2="24"
                        stroke={COLOR}
                        strokeWidth="3"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                    <line
                        x1="18"
                        y1="32"
                        x2="30"
                        y2="32"
                        stroke={FAINT}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.5"
                    />
                </svg>
            )
        default:
            return (
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="24" cy="24" r="14" stroke={FAINT} strokeWidth="1.5" fill="none" />
                    <line
                        x1="18"
                        y1="24"
                        x2="30"
                        y2="24"
                        stroke={COLOR}
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        opacity="0.3"
                    />
                </svg>
            )
    }
}
